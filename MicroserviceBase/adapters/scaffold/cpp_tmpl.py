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
    grpc_name = _grpc_svc_name(spec)  # e.g. "HelloService" or "AnalogInputService"
    files["CMakeLists.txt"] = _cmake(spec)
    files["src/main.cpp"] = _main_cpp(spec)
    files["src/Settings.h"] = _settings_h(spec)
    files[f"src/domain/{grpc_name}.h"]   = _domain_h(spec)
    files[f"src/domain/{grpc_name}.cpp"] = _domain_cpp(spec)
    files[f"src/adapters/api/{spec.service_name}GrpcAdapter.h"]   = _adapter_h(spec)
    files[f"src/adapters/api/{spec.service_name}GrpcAdapter.cpp"] = _adapter_cpp(spec)

    # Central env var file — all build scripts source this so the user
    # only has to configure paths in one place.
    files["set_env.bat"] = _set_env_bat(spec)
    files["set_env.sh"] = _set_env_sh(spec)
    # MinGW flavor uses its own set_env so MSVC defaults don't clobber
    # MinGW values (the files are now authoritative, no 'if not defined').
    files["set_env_mingw.bat"] = _set_env_mingw_bat(spec)

    # Generate stubs scripts go in proto/ (shared by service + client)
    files["proto/generate_stubs.bat"] = _gen_stubs_bat(spec)
    files["proto/generate_stubs.sh"] = _gen_stubs_sh(spec)

    if spec.gen_build_scripts:
        files["build_deploy.bat"] = _build_bat(spec)
        files["build_deploy.sh"] = _build_sh(spec)
        # MinGW variant — uses vcpkg + x64-mingw-dynamic triplet.
        files["build_deploy_mingw.bat"] = _build_mingw_bat(spec)
        # MSYS2 variant — uses MSYS2's pacman tree (more reliable than
        # vcpkg+MinGW, which has community-tier port support).
        files["build_deploy_msys2.bat"] = _build_msys2_bat(spec)
        files["set_env_msys2.bat"] = _set_env_msys2_bat(spec)

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
    """CamelCase → snake_case, keeping runs of capitals together.

    ``MyService`` → ``my_service``, ``PPSService`` → ``pps_service``,
    ``XMLParser`` → ``xml_parser``, ``HTTPServer2`` → ``http_server2``.
    """
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _upper(name: str) -> str:
    return _snake(name).upper()


def _grpc_svc_name(spec: "ScaffoldSpec") -> str:
    """Canonical gRPC service class + domain class name for the single-service
    scaffold.  This is also used as the stem for the domain .h/.cpp files.

    - **Imported .proto** (``spec.proto_content_override`` is set): the user's
      proto already declares ``service <name> { ... }`` — use ``service_name``
      verbatim so we don't produce ``<name>Service`` which wouldn't exist.
    - **Wizard-generated proto**: :func:`shared.gen_proto` emits
      ``service <name>Service {{ ... }}``; append ``Service`` to match.
    """
    if spec.proto_content_override:
        return spec.service_name
    return f"{spec.service_name}Service"


# -----------------------------------------------------------------------
# CMakeLists.txt
# -----------------------------------------------------------------------

def _cmake(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
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
    grpc_name = _grpc_svc_name(spec)
    exe_block = f'''
add_executable({sn}
    src/main.cpp
    src/Settings.h
    src/domain/{grpc_name}.h
    src/domain/{grpc_name}.cpp
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
    svc = spec.service_name
    grpc_name = _grpc_svc_name(spec)  # matches proto's `service X { ... }`
    return f'''#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "domain/{grpc_name}.h"
#include "adapters/api/{svc}GrpcAdapter.h"

int main() {{
    try {{
        {sn}::Settings settings;
        {sn}::{grpc_name} domain;
        {sn}::{svc}GrpcAdapter adapter(domain);

        microservice_base::ServiceRunner runner(settings, {{"v1"}});
        runner.addService(&adapter, "{pkg}.{grpc_name}");
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
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
    grpc_name = _grpc_svc_name(spec)

    imported = any(m.input_type or m.output_type for m in spec.methods)

    if imported:
        # Imported proto: we can't infer the right domain signatures.
        # Emit an empty class; the user adds methods matching their proto.
        return f'''#pragma once

#include <string>

namespace {sn} {{

class {grpc_name} {{
public:
    // TODO: add domain methods for your imported proto here.
}};

}}  // namespace {sn}
'''

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        methods += f"    std::string {_snake(m.name)}({params}) const;\n"

    return f'''#pragma once

#include <string>

namespace {sn} {{

class {grpc_name} {{
public:
{methods if methods else "    // Add methods here."}
}};

}}  // namespace {sn}
'''


def _domain_cpp(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    grpc_name = _grpc_svc_name(spec)

    imported = any(m.input_type or m.output_type for m in spec.methods)

    if imported:
        return f'''#include "{grpc_name}.h"

namespace {sn} {{

// TODO: add domain implementations for your imported proto here.

}}  // namespace {sn}
'''

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        methods += f'''
std::string {grpc_name}::{_snake(m.name)}({params}) const {{
    // TODO: implement
    return "not implemented";
}}
'''

    return f'''#include "{grpc_name}.h"

namespace {sn} {{
{methods if methods else "// Add implementations here."}
}}  // namespace {sn}
'''


# -----------------------------------------------------------------------
# gRPC Adapter
# -----------------------------------------------------------------------

def _adapter_h(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    svc = spec.service_name

    methods = ""
    for m in spec.methods:
        inT  = ("::" + m.input_type.replace(".", "::")) if m.input_type else f"{ns}::{m.name}Request"
        outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"
        if m.server_streaming:
            methods += (
                f"    grpc::Status {m.name}(grpc::ServerContext*,\n"
                f"        const {inT}*,\n"
                f"        grpc::ServerWriter<{outT}>*) override;\n\n"
            )
        else:
            methods += (
                f"    grpc::Status {m.name}(grpc::ServerContext*,\n"
                f"        const {inT}*,\n"
                f"        {outT}*) override;\n\n"
            )

    grpc_name = _grpc_svc_name(spec)
    return f'''#pragma once

#include <grpcpp/grpcpp.h>
#include "{sn}.grpc.pb.h"
#include "domain/{grpc_name}.h"

namespace {sn} {{

class {svc}GrpcAdapter final : public {ns}::{grpc_name}::Service {{
public:
    explicit {svc}GrpcAdapter({grpc_name}& domain) : m_domain(domain) {{}}

{methods}
private:
    {grpc_name}& m_domain;
}};

}}  // namespace {sn}
'''


def _adapter_cpp(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    svc = spec.service_name
    grpc_name = _grpc_svc_name(spec)

    methods = ""
    for m in spec.methods:
        imported = bool(m.input_type or m.output_type)
        inT  = ("::" + m.input_type.replace(".", "::")) if m.input_type else f"{ns}::{m.name}Request"
        outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"

        if imported:
            # Imported proto: can't infer field names, emit UNIMPLEMENTED stub.
            if m.server_streaming:
                methods += f'''
grpc::Status {svc}GrpcAdapter::{m.name}(
    grpc::ServerContext* /*ctx*/,
    const {inT}* /*request*/,
    grpc::ServerWriter<{outT}>* /*writer*/) {{
    // TODO: stream {outT} responses to the writer based on `request` + m_domain.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement {m.name}");
}}
'''
            else:
                methods += f'''
grpc::Status {svc}GrpcAdapter::{m.name}(
    grpc::ServerContext* /*ctx*/,
    const {inT}* /*request*/,
    {outT}* /*response*/) {{
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement {m.name}");
}}
'''
            continue

        param_reads = "\n".join(
            f"    auto _{p.name} = request->{p.name}();"
            for p in m.params
        )
        args = ", ".join(f"_{p.name}" for p in m.params)

        if m.server_streaming:
            methods += f'''
grpc::Status {svc}GrpcAdapter::{m.name}(
    grpc::ServerContext* ctx,
    const {inT}* request,
    grpc::ServerWriter<{outT}>* writer) {{
{param_reads}
    // TODO: implement streaming
    {outT} resp;
    resp.set_result(m_domain.{_snake(m.name)}({args}));
    writer->Write(resp);
    return grpc::Status::OK;
}}
'''
        else:
            methods += f'''
grpc::Status {svc}GrpcAdapter::{m.name}(
    grpc::ServerContext*,
    const {inT}* request,
    {outT}* response) {{
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
    """MSVC flavor of set_env.bat — authoritative (no 'if not defined')."""
    qt_line = ""
    qt_summary = ""
    if spec.gui_type in ("widget", "wasm"):
        qt_line = 'set "QT_DIR=C:\\Qt\\6.7.1\\msvc2019_64"\n'
        qt_summary = 'echo   QT_DIR     = %QT_DIR%\n'

    wasm_block = ""
    wasm_summary = ""
    if spec.gui_type == "wasm":
        wasm_block = '''
:: ----- Qt / Emscripten paths (only needed for WASM GUI builds) -----
set "QT_WASM_DIR=C:\\Qt\\6.7.1\\wasm_singlethread"
set "QT_HOST_DIR=C:\\Qt\\6.7.1\\msvc2019_64"
set "QT_CMAKE_DIR=C:\\Qt\\Tools\\CMake_64\\bin"
set "QT_NINJA_DIR=C:\\Qt\\Tools\\Ninja"
set "EMSDK_DIR=D:\\emsdk"
'''
        wasm_summary = (
            'echo   QT_WASM_DIR  = %QT_WASM_DIR%\n'
            'echo   QT_HOST_DIR  = %QT_HOST_DIR%\n'
            'echo   QT_CMAKE_DIR = %QT_CMAKE_DIR%\n'
            'echo   QT_NINJA_DIR = %QT_NINJA_DIR%\n'
            'echo   EMSDK_DIR    = %EMSDK_DIR%\n'
        )

    return f'''@echo off
:: Central environment for MSVC builds.
::
:: THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.
:: Edit them directly to match your machine — that way a previous bad
:: 'set' in the shell can't stick around and break subsequent runs.
::
:: For MinGW builds use set_env_mingw.bat instead (called by
:: build_deploy_mingw.bat).

set "VCPKG_ROOT=C:\\vcpkg"

:: CMake / Ninja — absolute paths; prepended to PATH if the exe exists.
set "CMAKE_DIR=C:\\Program Files\\CMake\\bin"
set "NINJA_DIR="

if exist "%CMAKE_DIR%\\cmake.exe" set "PATH=%CMAKE_DIR%;%PATH%"
if defined NINJA_DIR if exist "%NINJA_DIR%\\ninja.exe" set "PATH=%NINJA_DIR%;%PATH%"

:: MSVC compiler — call vcvars64.bat to set cl.exe, link.exe, Windows SDK.
:: Skip if already initialised (VSCMD_ARG_TGT_ARCH is set by vcvars itself).
set "VS_DEV_CMD=C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat"
if not defined VSCMD_ARG_TGT_ARCH (
    if exist "%VS_DEV_CMD%" (
        call "%VS_DEV_CMD%" >nul
    )
)
{qt_line}{wasm_block}
set "MSBASE_ENV_LOADED=msvc"

echo ==== set_env (MSVC) applied ====
echo   VCPKG_ROOT = %VCPKG_ROOT%
echo   CMAKE_DIR  = %CMAKE_DIR%
echo   NINJA_DIR  = %NINJA_DIR%
echo   VS_DEV_CMD = %VS_DEV_CMD%
{qt_summary}{wasm_summary}echo ==================================
'''


def _set_env_mingw_bat(spec: "ScaffoldSpec") -> str:
    """MinGW flavor of set_env.bat — authoritative (no 'if not defined')."""
    qt_line = ""
    qt_summary = ""
    if spec.gui_type in ("widget", "wasm"):
        qt_line = 'set "QT_DIR=C:\\Qt\\6.7.1\\mingw_64"\n'
        qt_summary = 'echo   QT_DIR        = %QT_DIR%\n'

    return f'''@echo off
:: Central environment for MinGW builds.
::
:: THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.
:: Edit them directly to match your machine.
::
:: Called by build_deploy_mingw.bat; do NOT mix with build_deploy.bat
:: (which uses set_env.bat + MSVC).

set "VCPKG_ROOT=C:\\vcpkg"
set "VCPKG_TRIPLET=x64-mingw-dynamic"
set "MINGW_DIR=C:\\Qt\\Tools\\mingw1120_64\\bin"
set "NINJA_DIR=C:\\Qt\\Tools\\Ninja"
set "CMAKE_DIR=C:\\Program Files\\CMake\\bin"
{qt_line}
if exist "%MINGW_DIR%\\g++.exe"   set "PATH=%MINGW_DIR%;%PATH%"
if exist "%NINJA_DIR%\\ninja.exe" set "PATH=%NINJA_DIR%;%PATH%"
if exist "%CMAKE_DIR%\\cmake.exe" set "PATH=%CMAKE_DIR%;%PATH%"

set "MSBASE_ENV_LOADED=mingw"

echo ==== set_env (MinGW) applied ====
echo   VCPKG_ROOT    = %VCPKG_ROOT%
echo   VCPKG_TRIPLET = %VCPKG_TRIPLET%
echo   MINGW_DIR     = %MINGW_DIR%
echo   NINJA_DIR     = %NINJA_DIR%
echo   CMAKE_DIR     = %CMAKE_DIR%
{qt_summary}echo ==================================
'''


def _set_env_sh(spec: "ScaffoldSpec") -> str:
    qt_line = ""
    qt_summary = ""
    if spec.gui_type in ("widget", "wasm"):
        qt_line = 'export QT_DIR="$HOME/Qt/6.7.1/gcc_64"\n'
        qt_summary = 'echo "  QT_DIR     = $QT_DIR"\n'

    wasm_block = ""
    wasm_summary = ""
    if spec.gui_type == "wasm":
        wasm_block = '''
# ----- Qt / Emscripten paths (only needed for WASM GUI builds) -----
export QT_WASM_DIR="$HOME/Qt/6.7.1/wasm_singlethread"
export QT_HOST_DIR="$HOME/Qt/6.7.1/gcc_64"
export EMSDK_DIR="$HOME/emsdk"
'''
        wasm_summary = (
            'echo "  QT_WASM_DIR = $QT_WASM_DIR"\n'
            'echo "  QT_HOST_DIR = $QT_HOST_DIR"\n'
            'echo "  EMSDK_DIR   = $EMSDK_DIR"\n'
        )

    return f'''#!/usr/bin/env bash
# Central environment for native (gcc/clang) builds.
#
# THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.  Edit
# them directly to match your machine — that way a previous bad export
# can't stick around and break subsequent runs.

export VCPKG_ROOT="$HOME/vcpkg"

# CMake / Ninja — absolute paths (leave empty to use system PATH).
export CMAKE_DIR=""
export NINJA_DIR=""
[ -n "$CMAKE_DIR" ] && [ -x "$CMAKE_DIR/cmake" ] && export PATH="$CMAKE_DIR:$PATH"
[ -n "$NINJA_DIR" ] && [ -x "$NINJA_DIR/ninja" ] && export PATH="$NINJA_DIR:$PATH"

# Compiler — leave empty for the system default (gcc/clang).
export CC=""
export CXX=""
{qt_line}{wasm_block}
echo "==== set_env applied ===="
echo "  VCPKG_ROOT = $VCPKG_ROOT"
echo "  CMAKE_DIR  = $CMAKE_DIR"
echo "  NINJA_DIR  = $NINJA_DIR"
echo "  CC / CXX   = $CC / $CXX"
{qt_summary}{wasm_summary}echo "========================="
'''


# -----------------------------------------------------------------------
# Build scripts
# -----------------------------------------------------------------------

def _build_bat(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
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
    ns = spec.proto_namespace
    pkg = spec.proto_package

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
::   - Points QT_DIR at the Qt MinGW kit
::
:: All paths come from set_env_mingw.bat (edit that file for your machine).
::
:: First-time vcpkg install for the mingw triplet can take 20-60 min
:: (ports compile from source).  Pre-seed with:
::     "%VCPKG_ROOT%\\vcpkg" install grpc:x64-mingw-dynamic protobuf:x64-mingw-dynamic curl:x64-mingw-dynamic
setlocal

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env_mingw.bat"

where g++ >nul 2>&1
if errorlevel 1 ( echo ERROR: g++ not found.  Check MINGW_DIR in set_env_mingw.bat & exit /b 1 )
where ninja >nul 2>&1
if errorlevel 1 ( echo ERROR: ninja not found.  Check NINJA_DIR in set_env_mingw.bat & exit /b 1 )

:: Verify the mingw-dynamic vcpkg triplet actually has grpc installed.
:: Without this, find_package falls back to the x64-windows (MSVC) prefix
:: and the link fails with MSVC-only flags like '-ignore:4221'.
if not exist "%VCPKG_ROOT%\\installed\\%VCPKG_TRIPLET%\\share\\grpc" (
    echo.
    echo ERROR: vcpkg packages for triplet "%VCPKG_TRIPLET%" are not installed.
    echo.
    echo        Run this once (first time can take 20-60 min^):
    echo.
    echo          set VCPKG_DEFAULT_TRIPLET=%VCPKG_TRIPLET%
    echo          "%VCPKG_ROOT%\\vcpkg" install grpc:%VCPKG_TRIPLET% protobuf:%VCPKG_TRIPLET% curl:%VCPKG_TRIPLET%
    echo.
    exit /b 1
)

:: ----- Generate proto stubs (FORCE regenerate with MinGW protoc) -----
:: Proto stubs are toolchain-ABI-sensitive: stubs produced by a different
:: toolchain's protoc won't compile against this toolchain's protobuf
:: headers.  Always regenerate so they match the active install.
del /q "%SCRIPT_DIR%proto\\{sn}.pb.h"       >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.pb.cc"      >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.h"  >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.cc" >nul 2>&1
call "%SCRIPT_DIR%proto\\generate_stubs.bat"
if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )

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


# -----------------------------------------------------------------------
# MSYS2 variant (pacman packages — most reliable MinGW path on Windows)
# -----------------------------------------------------------------------

def _set_env_msys2_bat(spec: "ScaffoldSpec") -> str:
    """MSYS2 env setup — uses MSYS2's mingw64 tree for toolchain + deps."""
    return '''@echo off
:: Central environment for MSYS2 / MinGW builds.
::
:: Uses MSYS2's native MinGW packages (installed via pacman) instead of
:: vcpkg — more reliable MinGW story on Windows.
::
:: One-time setup:
::   1. Install MSYS2 from https://www.msys2.org/ (default path: C:\\msys64)
::   2. Install the required packages:
::        C:\\msys64\\usr\\bin\\pacman -S --needed ^
::           mingw-w64-x86_64-gcc ^
::           mingw-w64-x86_64-cmake ^
::           mingw-w64-x86_64-ninja ^
::           mingw-w64-x86_64-grpc ^
::           mingw-w64-x86_64-protobuf ^
::           mingw-w64-x86_64-curl ^
::           mingw-w64-x86_64-qt6-base ^
::           mingw-w64-x86_64-qt6-tools
::
:: THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.

set "MSYS2_ROOT=C:\\msys64\\mingw64"
set "QT_DIR=%MSYS2_ROOT%"

set "PATH=%MSYS2_ROOT%\\bin;%PATH%"

set "MSBASE_ENV_LOADED=msys2"

echo ==== set_env (MSYS2) applied ====
echo   MSYS2_ROOT = %MSYS2_ROOT%
echo   QT_DIR     = %QT_DIR%
echo ==================================
'''


def _build_msys2_bat(spec: "ScaffoldSpec") -> str:
    """MSYS2 deploy script — uses MSYS2's native MinGW packages."""
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package

    windeployqt_block = ""
    if spec.gui_type == "widget":
        windeployqt_block = f'''
:: ----- Deploy Qt runtime for the GUI (MSYS2 ships windeployqt with qt6-tools) -----
if exist "%DIST%\\{sn}_gui.exe" (
    if exist "%MSYS2_ROOT%\\bin\\windeployqt-qt6.exe" (
        echo Running windeployqt-qt6 for {sn}_gui.exe ...
        "%MSYS2_ROOT%\\bin\\windeployqt-qt6.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\\{sn}_gui.exe" >nul
    ) else if exist "%MSYS2_ROOT%\\bin\\windeployqt.exe" (
        echo Running windeployqt for {sn}_gui.exe ...
        "%MSYS2_ROOT%\\bin\\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\\{sn}_gui.exe" >nul
    ) else (
        echo WARNING: windeployqt not found in %MSYS2_ROOT%\\bin
        echo          Install with:  pacman -S mingw-w64-x86_64-qt6-tools
    )
)
'''

    return f'''@echo off
:: MSYS2 variant of build_deploy.bat.
::
::   - Uses MSYS2's native MinGW toolchain (g++/cmake/ninja)
::   - Consumes MSYS2 pacman packages (grpc, protobuf, curl, Qt6)
::   - No vcpkg, no community-tier triplet gymnastics
::
:: Much more reliable than vcpkg+MinGW.  See set_env_msys2.bat for the
:: one-time pacman install.
setlocal

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env_msys2.bat"

where g++   >nul 2>&1 || ( echo ERROR: g++ not found.   Check MSYS2_ROOT in set_env_msys2.bat & exit /b 1 )
where ninja >nul 2>&1 || ( echo ERROR: ninja not found. Install: pacman -S mingw-w64-x86_64-ninja & exit /b 1 )
where cmake >nul 2>&1 || ( echo ERROR: cmake not found. Install: pacman -S mingw-w64-x86_64-cmake & exit /b 1 )

:: Verify MSYS2 has gRPC installed.
if not exist "%MSYS2_ROOT%\\share\\grpc" (
    echo.
    echo ERROR: MSYS2 package mingw-w64-x86_64-grpc is not installed.
    echo.
    echo        From a cmd or MSYS2 shell:
    echo          C:\\msys64\\usr\\bin\\pacman -S --needed ^
    echo            mingw-w64-x86_64-grpc mingw-w64-x86_64-protobuf mingw-w64-x86_64-curl ^
    echo            mingw-w64-x86_64-qt6-base mingw-w64-x86_64-qt6-tools
    echo.
    exit /b 1
)

:: ----- Generate proto stubs (FORCE regenerate with MSYS2 protoc) -----
:: Proto stubs are toolchain-ABI-sensitive: stubs produced by vcpkg's
:: protoc (often v21.x) won't compile against MSYS2's protobuf (v33+).
:: Always regenerate so they match the active install.
del /q "%SCRIPT_DIR%proto\\{sn}.pb.h"       >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.pb.cc"      >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.h"  >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.cc" >nul 2>&1
call "%SCRIPT_DIR%proto\\generate_stubs.bat"
if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )

:: ----- Build service -----
set "SERVICE_BUILD=%SCRIPT_DIR%build-msys2"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_PREFIX_PATH="%MSYS2_ROOT%;%QT_DIR%" ^
      ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build client -----
set "CLIENT_BUILD=%SCRIPT_DIR%client\\build-msys2"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -G Ninja ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_PREFIX_PATH="%MSYS2_ROOT%;%QT_DIR%" ^
      ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect binaries + runtime DLLs into dist-msys2\\ -----
set "DIST=%SCRIPT_DIR%dist-msys2"
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%SERVICE_BUILD%\\*.exe" "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%SERVICE_BUILD%\\*.dll" "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\*.exe"  "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\*.dll"  "%DIST%\\" >nul 2>&1

:: MSYS2 runtime + dependency DLLs.
if exist "%MSYS2_ROOT%\\bin" (
    for %%L in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll zlib1.dll) do (
        if exist "%MSYS2_ROOT%\\bin\\%%L" copy /Y "%MSYS2_ROOT%\\bin\\%%L" "%DIST%\\" >nul
    )
    for %%G in (libgrpc libprotobuf libabsl libcares libre2 libssl libcrypto libcurl libidn2 libintl libiconv libpsl libunistring libzstd libbrotli libnghttp2 libssh2) do (
        xcopy /Y /Q "%MSYS2_ROOT%\\bin\\%%G*.dll" "%DIST%\\" >nul 2>&1
    )
)
{windeployqt_block}
echo.
echo MSYS2 build complete.  Binaries + runtime DLLs collected in: %DIST%
endlocal
'''


def _build_sh(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
    return f'''@echo off
:: Generate C++ gRPC stubs from {sn}.proto.
:: Run once, then both service and client can build without protoc.
setlocal enabledelayedexpansion

set "PROTO_DIR=%~dp0"
:: Remove trailing backslash
if "!PROTO_DIR:~-1!"=="\\" set "PROTO_DIR=!PROTO_DIR:~0,-1!"

:: Only call set_env.bat if the caller hasn't already loaded an env.
:: Re-sourcing would overwrite VCPKG_ROOT / PATH and pick the wrong
:: protoc (e.g. when called from build_deploy_mingw.bat / _msys2.bat).
if not defined MSBASE_ENV_LOADED (
    if exist "!PROTO_DIR!\\..\\set_env.bat" call "!PROTO_DIR!\\..\\set_env.bat"
)

:: ----- Find protoc and grpc_cpp_plugin -----
:: Prefer PATH (so the caller's chosen toolchain wins), fall back to vcpkg.
set "PROTOC="
set "GRPC_PLUGIN="

for /f "delims=" %%P in ('where protoc 2^>nul') do if "!PROTOC!"=="" set "PROTOC=%%P"
for /f "delims=" %%P in ('where grpc_cpp_plugin 2^>nul') do if "!GRPC_PLUGIN!"=="" set "GRPC_PLUGIN=%%P"

if "!PROTOC!"=="" if defined VCPKG_ROOT (
    if exist "!VCPKG_ROOT!\\installed\\x64-windows\\tools\\protobuf\\protoc.exe" (
        set "PROTOC=!VCPKG_ROOT!\\installed\\x64-windows\\tools\\protobuf\\protoc.exe"
    )
)
if "!GRPC_PLUGIN!"=="" if defined VCPKG_ROOT (
    if exist "!VCPKG_ROOT!\\installed\\x64-windows\\tools\\grpc\\grpc_cpp_plugin.exe" (
        set "GRPC_PLUGIN=!VCPKG_ROOT!\\installed\\x64-windows\\tools\\grpc\\grpc_cpp_plugin.exe"
    )
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
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

def _widget_method_binding(m: "MethodSpec", sn: str, ns: str) -> str:
    """Emit one `MethodBinding` initializer block for `buildMethodBindings()`.

    Picks the right widget cast + req setter per proto type, and the right
    display expression for the response's `result` field.  Supports unary
    and server-streaming RPCs.  For imported protos (``m.input_type``/
    ``m.output_type`` set) we can't infer field names so we emit a
    compile-only skeleton: default request, status-only response.
    """
    imported = bool(m.input_type or m.output_type)
    inT  = ("::" + m.input_type.replace(".", "::"))  if m.input_type  else f"{ns}::{m.name}Request"
    outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"

    if imported:
        # No params list — imported protos don't have the flat param shape;
        # user fills in req fields + result printing by hand.
        if m.server_streaming:
            return f'''    // --- {m.name} (imported proto, server streaming) ---
    {{
        MethodBinding b;
        b.name = "{m.name}";
        b.params = {{}};
        b.invoke = [this](const std::vector<QWidget*>& /*ws*/) -> QString {{
            grpc::ClientContext ctx;
            {inT} req;   // TODO: fill request fields
            auto reader = m_client->stub().{m.name}(&ctx, req);
            {outT} resp;
            int count = 0;
            while (reader->Read(&resp)) ++count;
            auto st = reader->Finish();
            if (!st.ok()) return QString("[error] ") + QString::fromStdString(st.error_message());
            return QString("({m.name}: %1 messages — fill in response formatting)").arg(count);
        }};
        m_methods.push_back(std::move(b));
    }}'''
        return f'''    // --- {m.name} (imported proto) ---
    {{
        MethodBinding b;
        b.name = "{m.name}";
        b.params = {{}};
        b.invoke = [this](const std::vector<QWidget*>& /*ws*/) -> QString {{
            grpc::ClientContext ctx;
            {inT} req;    // TODO: fill request fields
            {outT} resp;
            auto st = m_client->stub().{m.name}(&ctx, req, &resp);
            if (!st.ok()) return QString("[error] ") + QString::fromStdString(st.error_message());
            return "{m.name}: OK (fill in response formatting)";
        }};
        m_methods.push_back(std::move(b));
    }}'''

    # ---- Wizard-generated proto (flat params, `result` field) ----
    params_init = ", ".join(
        f'{{"{p.name}", "{p.type}"}}' for p in m.params
    )

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
            {inT} req;
{setters_str}
            auto reader = m_client->stub().{m.name}(&ctx, req);
            {outT} resp;
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
            {inT} req;
{setters_str}
            {outT} resp;
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
    grpc_name = _grpc_svc_name(spec)

    method_blocks = "\n\n".join(
        _widget_method_binding(m, sn, ns) for m in spec.methods
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
        microservice_base::ServiceClient<{ns}::{grpc_name}>> m_client;
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
                microservice_base::ServiceClient<{ns}::{grpc_name}>>("{sn}");
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
    ns = spec.proto_namespace
    pkg = spec.proto_package
    svc = spec.service_name
    prefix = spec.env_prefix
    grpc_name = _grpc_svc_name(spec)

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

using {ns}::{grpc_name};

int main(int argc, char* argv[]) {{
    if (argc < 2) {{
        std::cerr << "Usage: {sn}_client <service_name|--direct host:port> [method] [args...]" << std::endl;
        return 1;
    }}

    std::string arg1 = argv[1];
    std::unique_ptr<microservice_base::ServiceClient<{grpc_name}>> client;

    try {{
        if (arg1 == "--direct") {{
            if (argc < 3) {{ std::cerr << "Missing host:port" << std::endl; return 1; }}
            client = std::make_unique<microservice_base::ServiceClient<{grpc_name}>>(
                "{sn}", argv[2], true);
            std::cout << "Connected directly to " << client->target() << std::endl;
        }} else {{
            client = std::make_unique<microservice_base::ServiceClient<{grpc_name}>>(arg1);
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
    // {ns}::DoSomethingRequest req;
    // req.set_input("test");
    // {ns}::DoSomethingResponse resp;
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
Uses `ServiceClient<{grpc_name}>` from MicroserviceBase runtime for
automatic Consul discovery and channel management.
''',
    }


# =======================================================================
# Monorepo mode — single project folder, N services build into N .exe's
# =======================================================================

def _mono_snake(name: str) -> str:
    """Same smart snake-case as :func:`_snake` — keeps acronym runs
    together (``PPSService`` → ``pps_service``)."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def generate_monorepo(spec: "ScaffoldSpec", services) -> Dict[str, str]:
    """Emit a single-project scaffold with one executable per service.

    All services share one proto (written verbatim from spec.proto_content_override
    or regenerated), one CMakeLists.txt with N add_executable() calls, and
    a single build_deploy.bat that drops every .exe into dist/.

    `services` is a list of ServiceBlock (name + methods).
    v1: C++ only, no client subproject, no Qt widget GUI per service.
    """
    files: Dict[str, str] = {}
    project_name = spec.service_name        # used as the project folder & CMake project
    project_snake = spec.snake_name         # used for shared .proto filename

    # ------ Shared proto ------
    if spec.proto_content_override:
        files[f"proto/{project_snake}.proto"] = spec.proto_content_override
    else:
        # Fallback: build a merged proto from all services.  This preserves
        # semantic correctness even when the user didn't import a .proto.
        files[f"proto/{project_snake}.proto"] = _mono_gen_proto(spec, services)

    files["proto/generate_stubs.bat"] = _gen_stubs_bat(spec)
    files["proto/generate_stubs.sh"] = _gen_stubs_sh(spec)

    # ------ set_env.bat + variants ------
    files["set_env.bat"] = _set_env_bat(spec)
    files["set_env.sh"] = _set_env_sh(spec)
    files["set_env_mingw.bat"] = _set_env_mingw_bat(spec)
    files["set_env_msys2.bat"] = _set_env_msys2_bat(spec)

    # ------ Root CMakeLists.txt ------
    files["CMakeLists.txt"] = _mono_cmake(spec, services)

    # ------ Per-service source tree ------
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        svc_pascal = svc.name   # verbatim — already includes any "Service" suffix
        files[f"src/{svc_snake}/main.cpp"] = _mono_main_cpp(spec, svc)
        files[f"src/{svc_snake}/Settings.h"] = _mono_settings_h(spec, svc)
        files[f"src/{svc_snake}/domain/{svc_pascal}.h"] = _mono_domain_h(spec, svc)
        files[f"src/{svc_snake}/domain/{svc_pascal}.cpp"] = _mono_domain_cpp(spec, svc)
        files[f"src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.h"] = _mono_adapter_h(spec, svc)
        files[f"src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.cpp"] = _mono_adapter_cpp(spec, svc)

    # ------ Nomad jobs (one per service) ------
    if spec.gen_nomad:
        for svc in services:
            svc_snake = _mono_snake(svc.name)
            files[f"deploy/{svc_snake}.nomad.hcl"] = _mono_nomad(spec, svc)

    # ------ service_config.json (one per service) ------
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        files[f"deploy/{svc_snake}_service_config.json"] = _mono_service_config(spec, svc)

    # ------ build_deploy.bat / .sh + MinGW + MSYS2 variants ------
    if spec.gen_build_scripts:
        files["build_deploy.bat"] = _mono_build_bat(spec, services)
        files["build_deploy.sh"] = _mono_build_sh(spec, services)
        files["build_deploy_mingw.bat"] = _mono_build_mingw_bat(spec, services)
        files["build_deploy_msys2.bat"] = _mono_build_msys2_bat(spec, services)

    # ------ Client subproject (one test binary per service) ------
    files.update(_mono_client_files(spec, services))

    # ------ README ------
    if spec.gen_readme:
        files["README.md"] = _mono_readme(spec, services)

    # ------ Pre-generate C++ proto stubs server-side (optional) ------
    # Handled by the caller via _generate_cpp_stubs if spec.gen_stubs; we
    # include an empty marker so the post-processing picks it up.
    return files


# ----------------------------------------------------------------------
# Monorepo helpers
# ----------------------------------------------------------------------

def _mono_gen_proto(spec, services) -> str:
    """Fallback proto generator for monorepo (when user didn't import)."""
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    lines = [
        'syntax = "proto3";',
        '',
        f'package {pkg};',
        '',
    ]
    for svc in services:
        # Use svc.name verbatim — caller supplies the full service identifier
        # (imported protos already include any "Service" suffix the user chose).
        lines.append(f'service {svc.name} {{')
        for m in svc.methods:
            stream = "stream " if m.server_streaming else ""
            lines.append(f'  rpc {m.name} ({m.name}Request) returns ({stream}{m.name}Response);')
        lines.append('}')
        lines.append('')
        for m in svc.methods:
            lines.append(f'message {m.name}Request {{')
            for i, p in enumerate(m.params, 1):
                # Minimal type map for the fallback path.
                t = {'string': 'string', 'int32': 'int32', 'int64': 'int64',
                     'bool': 'bool', 'float': 'float', 'double': 'double',
                     'bytes': 'bytes'}.get((p.type or 'string').lower(), 'string')
                lines.append(f'  {t} {p.name} = {i};')
            if not m.params:
                lines.append('  // no parameters')
            lines.append('}')
            lines.append('')
            rt = {'string': 'string', 'int32': 'int32', 'int64': 'int64',
                  'bool': 'bool', 'float': 'float', 'double': 'double',
                  'bytes': 'bytes'}.get((m.return_type or 'string').lower(), 'string')
            lines.append(f'message {m.name}Response {{')
            lines.append(f'  {rt} result = 1;')
            lines.append('}')
            lines.append('')
    return '\n'.join(lines)


def _mono_cmake(spec, services) -> str:
    project_name = spec.service_name
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    proto_srcs_var = f"{sn.upper()}_PROTO_SRCS"
    proto_inc_var  = f"{sn.upper()}_PROTO_INC"

    exe_blocks = []
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        svc_pascal = svc.name
        exe_blocks.append(f'''
# ---- {svc_pascal} ----
add_executable({svc_snake}
    src/{svc_snake}/main.cpp
    src/{svc_snake}/domain/{svc_pascal}.cpp
    src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.cpp
    ${{{proto_srcs_var}}}
)
target_include_directories({svc_snake} PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src/{svc_snake}"
    "${{{proto_inc_var}}}"
)
target_link_libraries({svc_snake} PRIVATE
    microservice_base::runtime
    gRPC::grpc++ gRPC::grpc++_reflection
    protobuf::libprotobuf
)
'''.rstrip())

    exe_joined = '\n'.join(exe_blocks)

    return f'''cmake_minimum_required(VERSION 3.16)
project({project_name} VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Auto-detect vcpkg from VCPKG_ROOT env var.
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected)")
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
find_package(CURL     CONFIG REQUIRED)

# Shared MicroserviceBase runtime.
add_subdirectory(
    "${{CMAKE_CURRENT_SOURCE_DIR}}/../../MicroserviceBase/runtime_cpp"
    "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")

# ---- Proto stubs (shared by every service in this project) ----
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/proto")
if(EXISTS "${{PROTO_DIR}}/{sn}.pb.h")
    set({proto_srcs_var}
        "${{PROTO_DIR}}/{sn}.pb.cc"
        "${{PROTO_DIR}}/{sn}.grpc.pb.cc")
    set({proto_inc_var} "${{PROTO_DIR}}")
else()
    set(GEN_DIR "${{CMAKE_CURRENT_BINARY_DIR}}/gen")
    file(MAKE_DIRECTORY "${{GEN_DIR}}")
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
        DEPENDS "${{PROTO_DIR}}/{sn}.proto")
    set({proto_srcs_var}
        "${{GEN_DIR}}/{sn}.pb.cc"
        "${{GEN_DIR}}/{sn}.grpc.pb.cc")
    set({proto_inc_var} "${{GEN_DIR}}")
endif()

# ---- Per-service executables ----
{exe_joined}
'''


def _mono_main_cpp(spec, svc) -> str:
    sn = spec.snake_name  # proto package is derived from *project* snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    return f'''#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "domain/{svc_pascal}.h"
#include "adapters/api/{svc_pascal}GrpcAdapter.h"

int main() {{
    try {{
        {svc_snake}::Settings settings;
        {svc_snake}::{svc_pascal} domain;
        {svc_snake}::{svc_pascal}GrpcAdapter adapter(domain);

        microservice_base::ServiceRunner runner(settings, {{"v1"}});
        runner.addService(&adapter, "{pkg}.{svc_pascal}");
        runner.serveForever();
    }} catch (const std::exception& e) {{
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }}
    return 0;
}}
'''


def _mono_settings_h(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    prefix = svc_snake.upper() + "_"
    return f'''#pragma once

#include "MicroserviceBase/Settings.h"

namespace {svc_snake} {{

struct Settings : public microservice_base::BaseServiceSettings {{
    Settings() {{
        service_name = "{svc_snake}";
        loadBaseFromEnv("{prefix}");
    }}
}};

}}  // namespace {svc_snake}
'''


def _mono_domain_h(spec, svc) -> str:
    """Domain class is a placeholder — the user adds methods matching
    their proto's real request/response fields.  We intentionally don't
    guess signatures because we can't map arbitrary imported protos."""
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    method_hints = "\n".join(
        f"    // rpc {m.name}(...)  -  wire in adapters/api/{svc_pascal}GrpcAdapter.cpp"
        for m in svc.methods
    ) or "    // (no methods declared in proto yet)"
    return f'''#pragma once

// Domain layer for {svc.name}.
//
// Pure C++ — no gRPC, no Consul.  Add one method per RPC:
//   - signature matches your proto's request/response fields
//   - the adapter in adapters/api/ marshals between proto and these
//     method arguments / return values.

#include <string>

namespace {svc_snake} {{

class {svc_pascal} {{
public:
    // TODO: add your methods here.  Expected API surface:
{method_hints}
}};

}}  // namespace {svc_snake}
'''


def _mono_domain_cpp(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    return f'''#include "{svc_pascal}.h"

namespace {svc_snake} {{

// TODO: implement your domain methods here.

}}  // namespace {svc_snake}
'''


def _mono_input_cpp_type(m, ns_fallback) -> str:
    """C++ type string for a method's input message.  Prefers m.input_type
    (fully-qualified from imported proto), else <ns>::<Method>Request."""
    if m.input_type:
        return "::" + m.input_type.replace(".", "::")
    return f"{ns_fallback}::{m.name}Request"


def _mono_output_cpp_type(m, ns_fallback) -> str:
    if m.output_type:
        return "::" + m.output_type.replace(".", "::")
    return f"{ns_fallback}::{m.name}Response"


def _mono_adapter_h(spec, svc) -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    methods = ""
    for m in svc.methods:
        inT  = _mono_input_cpp_type(m, ns)
        outT = _mono_output_cpp_type(m, ns)
        if m.server_streaming:
            methods += (
                f"    grpc::Status {m.name}(grpc::ServerContext*,\n"
                f"        const {inT}*,\n"
                f"        grpc::ServerWriter<{outT}>*) override;\n\n"
            )
        else:
            methods += (
                f"    grpc::Status {m.name}(grpc::ServerContext*,\n"
                f"        const {inT}*,\n"
                f"        {outT}*) override;\n\n"
            )
    return f'''#pragma once

#include <grpcpp/grpcpp.h>
#include "{sn}.grpc.pb.h"
#include "domain/{svc_pascal}.h"

namespace {svc_snake} {{

class {svc_pascal}GrpcAdapter final : public {ns}::{svc_pascal}::Service {{
public:
    explicit {svc_pascal}GrpcAdapter({svc_pascal}& domain) : m_domain(domain) {{}}

{methods}
private:
    {svc_pascal}& m_domain;
}};

}}  // namespace {svc_snake}
'''


def _mono_adapter_cpp(spec, svc) -> str:
    """Adapter bodies are placeholders — user fills in marshaling logic.

    For arbitrary imported protos we can't infer how the user's domain
    class maps to their specific request/response fields, so we emit a
    safe-compiling `UNIMPLEMENTED` stub with TODO markers.
    """
    ns = spec.proto_namespace
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    methods = ""
    for m in svc.methods:
        inT  = _mono_input_cpp_type(m, ns)
        outT = _mono_output_cpp_type(m, ns)
        if m.server_streaming:
            methods += f'''
grpc::Status {svc_pascal}GrpcAdapter::{m.name}(
    grpc::ServerContext* /*ctx*/,
    const {inT}* /*request*/,
    grpc::ServerWriter<{outT}>* /*writer*/) {{
    // TODO: stream {outT} responses to the writer based on `request` + m_domain.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement {m.name}");
}}
'''
        else:
            methods += f'''
grpc::Status {svc_pascal}GrpcAdapter::{m.name}(
    grpc::ServerContext* /*ctx*/,
    const {inT}* /*request*/,
    {outT}* /*response*/) {{
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement {m.name}");
}}
'''
    return f'''#include "{svc_pascal}GrpcAdapter.h"

namespace {svc_snake} {{
{methods}
}}  // namespace {svc_snake}
'''


def _mono_nomad(spec, svc) -> str:
    """Per-service Nomad HCL spec."""
    svc_snake = _mono_snake(svc.name)
    prefix = svc_snake.upper() + "_"
    dc = getattr(spec, 'nomad_dc', 'dc1') or 'dc1'
    driver = getattr(spec, 'nomad_driver', 'raw_exec') or 'raw_exec'
    cpu = getattr(spec, 'nomad_cpu', 100) or 100
    mem = getattr(spec, 'nomad_mem', 128) or 128
    consul_addr = getattr(spec, 'nomad_consul_addr', '') or 'http://127.0.0.1:8500'
    # On Windows + raw_exec, launching the .exe directly tends to die with
    # STATUS_DLL_NOT_FOUND (0xC0000135) — Nomad's `env` block doesn't actually
    # propagate PATH to the Windows DLL loader, and ${{PATH}} in that block
    # doesn't expand to the agent's OS PATH.
    #
    # Fix: invoke the `run_<svc>.bat` launcher that build_deploy_msys2.bat
    # writes into dist-msys2/.  The .bat prepends MSYS2's bin to the PATH
    # inherited from cmd.exe (which inherits the agent's full PATH,
    # including C:\Windows\system32), so DLL resolution Just Works.
    #
    # **Edit the absolute path below to match where you deployed the build.**
    # On Linux / macOS, replace the config block with a direct command to
    # the ELF binary — raw_exec on POSIX inherits PATH normally.
    return f'''# Nomad job for {svc.name} (part of {spec.service_name} monorepo).
job "{svc_snake}" {{
  datacenters = ["{dc}"]
  type        = "service"

  group "{svc_snake}" {{
    count = 1

    network {{
      port "grpc" {{}}   # dynamic port — Nomad picks a free one
    }}

    task "server" {{
      driver = "{driver}"

      # Windows: launch via the run_<svc>.bat that build_deploy_msys2.bat
      # emits into dist-msys2/.  Avoids 0xC0000135 DLL-load failures by
      # layering MSYS2's bin on top of the agent-inherited PATH.
      # Edit the absolute path to match where you deployed the project.
      config {{
        command = "cmd.exe"
        args    = ["/c", "C:/path/to/{spec.service_name}/dist-msys2/run_{svc_snake}.bat"]
      }}

      # On Linux use this instead (no PATH gymnastics needed):
      # config {{
      #   command = "/path/to/{svc_snake}"
      # }}

      env {{
        {prefix}GRPC_PORT      = "${{NOMAD_PORT_grpc}}"
        {prefix}ADVERTISE_ADDR = "127.0.0.1"
        {prefix}CONSUL_ADDR    = "{consul_addr}"
        {prefix}LOG_LEVEL      = "INFO"
      }}

      resources {{
        cpu    = {cpu}
        memory = {mem}
      }}
    }}
  }}
}}
'''


def _mono_service_config(spec, svc) -> str:
    import json
    svc_snake = _mono_snake(svc.name)
    cfg = {
        "name": svc_snake,
        "version": spec.version,
        "routing_key": svc_snake,
        "description": f"{svc.name} microservice (part of {spec.service_name}).",
        "shortdesc": svc.name,
        "group": spec.group or "Services",
        "tag": spec.tag or "",
        "gui_support": False,
        "downloadable": False,
    }
    return json.dumps(cfg, indent=4) + "\n"


def _mono_build_bat(spec, services) -> str:
    """MSVC build: services + client test binaries, collected into dist/."""
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    exe_copies = "\n".join(
        f'xcopy /Y /Q "%SERVICE_BUILD%\\Release\\{_mono_snake(s.name)}.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    client_copies = "\n".join(
        f'xcopy /Y /Q "%CLIENT_BUILD%\\Release\\{_mono_snake(s.name)}_client.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    return f'''@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env.bat"

:: ----- Generate proto stubs (idempotent) -----
if not exist "%SCRIPT_DIR%proto\\{sn}.pb.h" (
    call "%SCRIPT_DIR%proto\\generate_stubs.bat"
    if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )
)

:: ----- Build services -----
set "SERVICE_BUILD=%SCRIPT_DIR%build"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\\scripts\\buildsystems\\vcpkg.cmake" ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build . --config Release
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build client test binaries -----
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
set "DIST=%SCRIPT_DIR%dist"
if not exist "%DIST%" mkdir "%DIST%"
{exe_copies}
{client_copies}
xcopy /Y /Q "%SERVICE_BUILD%\\Release\\*.dll" "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\Release\\*.dll"  "%DIST%\\" >nul 2>&1

echo.
echo Build complete.  Binaries collected in: %DIST%
endlocal
'''


def _mono_build_sh(spec, services) -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    exe_copies = "\n".join(
        f'cp "$SERVICE_BUILD/{_mono_snake(s.name)}"        "$DIST/" 2>/dev/null || true'
        for s in services
    )
    client_copies = "\n".join(
        f'cp "$CLIENT_BUILD/{_mono_snake(s.name)}_client" "$DIST/" 2>/dev/null || true'
        for s in services
    )
    return f'''#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"

if [ ! -f "$SCRIPT_DIR/proto/{sn}.pb.h" ]; then
    bash "$SCRIPT_DIR/proto/generate_stubs.sh"
fi

# ----- Services -----
SERVICE_BUILD="$SCRIPT_DIR/build"
mkdir -p "$SERVICE_BUILD"
cmake -S "$SCRIPT_DIR" -B "$SERVICE_BUILD" \\
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \\
    -DCMAKE_BUILD_TYPE=Release
cmake --build "$SERVICE_BUILD" --parallel $(nproc)

# ----- Client test binaries -----
QT_PREFIX_ARG=()
if [ -n "${{QT_DIR:-}}" ]; then QT_PREFIX_ARG=(-DCMAKE_PREFIX_PATH="$QT_DIR"); fi
CLIENT_BUILD="$SCRIPT_DIR/client/build"
mkdir -p "$CLIENT_BUILD"
cmake -S "$SCRIPT_DIR/client" -B "$CLIENT_BUILD" \\
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \\
    "${{QT_PREFIX_ARG[@]}}" \\
    -DCMAKE_BUILD_TYPE=Release
cmake --build "$CLIENT_BUILD" --parallel $(nproc)

DIST="$SCRIPT_DIR/dist"
mkdir -p "$DIST"
{exe_copies}
{client_copies}

echo ""
echo "Monorepo build complete. Binaries in: $DIST"
'''


def _mono_readme(spec, services) -> str:
    svc_lines = "\n".join(
        f"- **{s.name}** — {len(s.methods)} method(s), env prefix `{_mono_snake(s.name).upper()}_`"
        for s in services
    )
    return f'''# {spec.service_name}

Monorepo containing {len(services)} gRPC services that share a single
`.proto` file and build from one CMakeLists.

## Services

{svc_lines}

## Layout

```
{spec.service_name}/
├── proto/{spec.snake_name}.proto     Shared API definition
├── src/<service>/                    One folder per service
├── deploy/<service>.nomad.hcl        One Nomad job per service
├── CMakeLists.txt                    Single CMake project
├── build_deploy.bat / .sh            One command builds all services
└── dist/                             Output: N .exe's + shared DLLs
```

## Build

```cmd
build_deploy.bat        :: Windows (MSVC)
./build_deploy.sh       # Linux
```

Each service is an independent executable listening on its own gRPC port
(see the `*_GRPC_PORT` env var per service).  All services register with
the same Consul agent by default.
'''


# ----------------------------------------------------------------------
# Monorepo: MinGW + MSYS2 build variants
# ----------------------------------------------------------------------

def _mono_build_mingw_bat(spec, services) -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    exe_copies = "\n".join(
        f'xcopy /Y /Q "%SERVICE_BUILD%\\{_mono_snake(s.name)}.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    client_copies = "\n".join(
        f'xcopy /Y /Q "%CLIENT_BUILD%\\{_mono_snake(s.name)}_client.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    return f'''@echo off
:: MinGW variant (vcpkg + x64-mingw-dynamic triplet).
setlocal
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env_mingw.bat"

where g++   >nul 2>&1 || ( echo ERROR: g++ not found.   & exit /b 1 )
where ninja >nul 2>&1 || ( echo ERROR: ninja not found. & exit /b 1 )

if not exist "%VCPKG_ROOT%\\installed\\%VCPKG_TRIPLET%\\share\\grpc" (
    echo ERROR: vcpkg packages for %VCPKG_TRIPLET% are not installed.
    echo        "%VCPKG_ROOT%\\vcpkg" install grpc:%VCPKG_TRIPLET% protobuf:%VCPKG_TRIPLET% curl:%VCPKG_TRIPLET%
    exit /b 1
)

:: ----- Force-regenerate stubs with MinGW protoc -----
del /q "%SCRIPT_DIR%proto\\{sn}.pb.h"       >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.pb.cc"      >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.h"  >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.cc" >nul 2>&1
call "%SCRIPT_DIR%proto\\generate_stubs.bat"
if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )

:: ----- Build services -----
set "SERVICE_BUILD=%SCRIPT_DIR%build-mingw"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\\scripts\\buildsystems\\vcpkg.cmake" ^
      -DVCPKG_TARGET_TRIPLET=%VCPKG_TRIPLET% ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build clients -----
set "CLIENT_BUILD=%SCRIPT_DIR%client\\build-mingw"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT%\\scripts\\buildsystems\\vcpkg.cmake" ^
      -DVCPKG_TARGET_TRIPLET=%VCPKG_TRIPLET% ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect -----
set "DIST=%SCRIPT_DIR%dist-mingw"
if not exist "%DIST%" mkdir "%DIST%"
{exe_copies}
{client_copies}
xcopy /Y /Q "%SERVICE_BUILD%\\*.dll" "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\*.dll"  "%DIST%\\" >nul 2>&1

if defined MINGW_DIR (
    for %%L in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll) do (
        if exist "%MINGW_DIR%\\%%L" copy /Y "%MINGW_DIR%\\%%L" "%DIST%\\" >nul
    )
)

echo.
echo MinGW monorepo build complete.  Binaries in: %DIST%
endlocal
'''


def _mono_build_msys2_bat(spec, services) -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    project_snake = sn
    exe_copies = "\n".join(
        f'xcopy /Y /Q "%SERVICE_BUILD%\\{_mono_snake(s.name)}.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    # Single unified client exe now (built in client/).  Kept separate so
    # the list can grow (e.g. a GUI client alongside the console one).
    client_copies_list = [
        f'xcopy /Y /Q "%CLIENT_BUILD%\\{project_snake}_client.exe" "%DIST%\\" >nul 2>&1'
    ]
    if spec.gui_type in ("widget", "wasm", "qml"):
        client_copies_list.append(
            f'xcopy /Y /Q "%CLIENT_BUILD%\\{project_snake}_gui.exe" "%DIST%\\" >nul 2>&1')
    client_copies = "\n".join(client_copies_list)

    # Runtime PATH launcher .bat per service (and per client exe).  On
    # Windows, silent "exe dies immediately" almost always means a transitive
    # DLL from MSYS2's mingw64/bin wasn't found — the build_deploy script
    # copies the big ones but not every transitive dep.  Prepending PATH is
    # bulletproof and doesn't require keeping the copy-list perfectly in sync
    # with MSYS2 package churn.
    launcher_names = [_mono_snake(s.name) for s in services]
    launcher_names.append(f"{project_snake}_client")
    if spec.gui_type in ("widget", "wasm", "qml"):
        launcher_names.append(f"{project_snake}_gui")

    # GUI launcher also sets QT_PLUGIN_PATH — without the Qt platform plugin
    # (qwindows.dll under `platforms/`) the GUI exits silently before `main`.
    gui_launcher_name = f"{project_snake}_gui" if spec.gui_type in ("widget", "wasm", "qml") else None

    launcher_lines = []
    for n in launcher_names:
        if n == gui_launcher_name:
            launcher_lines.append(
                f'call :emit_gui_launcher "%DIST%\\run_{n}.bat" "{n}.exe"')
        else:
            launcher_lines.append(
                f'call :emit_launcher "%DIST%\\run_{n}.bat" "{n}.exe"')
    launcher_block = "\n".join(launcher_lines)

    # Run windeployqt on the GUI exe so `dist-msys2/` is self-contained
    # (copies Qt DLLs + the platforms/qml/styles plugin dirs next to the exe).
    # Requires mingw-w64-x86_64-qt6-tools from pacman.
    windeployqt_block = ""
    if spec.gui_type in ("widget", "wasm"):
        windeployqt_block = f'''
:: ----- Deploy Qt runtime for the GUI client -----
if exist "%DIST%\\{project_snake}_gui.exe" (
    if exist "%MSYS2_ROOT%\\bin\\windeployqt-qt6.exe" (
        echo Running windeployqt-qt6 for {project_snake}_gui.exe ...
        "%MSYS2_ROOT%\\bin\\windeployqt-qt6.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\\{project_snake}_gui.exe" >nul
    ) else if exist "%MSYS2_ROOT%\\bin\\windeployqt.exe" (
        echo Running windeployqt for {project_snake}_gui.exe ...
        "%MSYS2_ROOT%\\bin\\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\\{project_snake}_gui.exe" >nul
    ) else (
        echo WARNING: windeployqt not found in %MSYS2_ROOT%\\bin
        echo          Install with:  pacman -S mingw-w64-x86_64-qt6-tools
        echo          GUI exe will rely on QT_PLUGIN_PATH from run_{project_snake}_gui.bat
    )
)
'''
    elif spec.gui_type == "qml":
        windeployqt_block = f'''
:: ----- Deploy Qt runtime + QML imports for the GUI client -----
if exist "%DIST%\\{project_snake}_gui.exe" (
    if exist "%MSYS2_ROOT%\\bin\\windeployqt-qt6.exe" (
        echo Running windeployqt-qt6 for {project_snake}_gui.exe ^(QML^)...
        "%MSYS2_ROOT%\\bin\\windeployqt-qt6.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime --qmldir "%SCRIPT_DIR%client\\gui" "%DIST%\\{project_snake}_gui.exe" >nul
    ) else if exist "%MSYS2_ROOT%\\bin\\windeployqt.exe" (
        "%MSYS2_ROOT%\\bin\\windeployqt.exe" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime --qmldir "%SCRIPT_DIR%client\\gui" "%DIST%\\{project_snake}_gui.exe" >nul
    ) else (
        echo WARNING: windeployqt not found in %MSYS2_ROOT%\\bin
        echo          Install with:  pacman -S mingw-w64-x86_64-qt6-tools
    )
)
'''
    return f'''@echo off
:: MSYS2 variant (native MinGW from pacman).
setlocal
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%set_env_msys2.bat"

where g++   >nul 2>&1 || ( echo ERROR: g++ not found.   & exit /b 1 )
where ninja >nul 2>&1 || ( echo ERROR: ninja not found. & exit /b 1 )
where cmake >nul 2>&1 || ( echo ERROR: cmake not found. & exit /b 1 )

if not exist "%MSYS2_ROOT%\\share\\grpc" (
    echo ERROR: MSYS2 package mingw-w64-x86_64-grpc is not installed.
    echo        C:\\msys64\\usr\\bin\\pacman -S --needed mingw-w64-x86_64-grpc mingw-w64-x86_64-protobuf mingw-w64-x86_64-curl
    exit /b 1
)

:: ----- Force-regenerate stubs with MSYS2 protoc -----
del /q "%SCRIPT_DIR%proto\\{sn}.pb.h"       >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.pb.cc"      >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.h"  >nul 2>&1
del /q "%SCRIPT_DIR%proto\\{sn}.grpc.pb.cc" >nul 2>&1
call "%SCRIPT_DIR%proto\\generate_stubs.bat"
if errorlevel 1 ( echo Stub generation failed. & exit /b 1 )

:: ----- Build services -----
set "SERVICE_BUILD=%SCRIPT_DIR%build-msys2"
if not exist "%SERVICE_BUILD%" mkdir "%SERVICE_BUILD%"
pushd "%SERVICE_BUILD%"
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_PREFIX_PATH="%MSYS2_ROOT%;%QT_DIR%" ..
if errorlevel 1 ( echo Service configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Service build failed. & popd & exit /b 1 )
popd

:: ----- Build clients -----
set "CLIENT_BUILD=%SCRIPT_DIR%client\\build-msys2"
if not exist "%CLIENT_BUILD%" mkdir "%CLIENT_BUILD%"
pushd "%CLIENT_BUILD%"
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_PREFIX_PATH="%MSYS2_ROOT%;%QT_DIR%" ..
if errorlevel 1 ( echo Client configure failed. & popd & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Client build failed. & popd & exit /b 1 )
popd

:: ----- Collect -----
set "DIST=%SCRIPT_DIR%dist-msys2"
if not exist "%DIST%" mkdir "%DIST%"
{exe_copies}
{client_copies}
xcopy /Y /Q "%SERVICE_BUILD%\\*.dll" "%DIST%\\" >nul 2>&1
xcopy /Y /Q "%CLIENT_BUILD%\\*.dll"  "%DIST%\\" >nul 2>&1

if exist "%MSYS2_ROOT%\\bin" (
    for %%L in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll zlib1.dll) do (
        if exist "%MSYS2_ROOT%\\bin\\%%L" copy /Y "%MSYS2_ROOT%\\bin\\%%L" "%DIST%\\" >nul
    )
    for %%G in (libgrpc libprotobuf libabsl libcares libre2 libssl libcrypto libcurl libidn2 libintl libiconv libpsl libunistring libzstd libbrotli libnghttp2 libssh2) do (
        xcopy /Y /Q "%MSYS2_ROOT%\\bin\\%%G*.dll" "%DIST%\\" >nul 2>&1
    )
)
{windeployqt_block}
:: ----- Emit run_*.bat launchers that ensure MSYS2 bin + Qt plugins are reachable -----
{launcher_block}

echo.
echo MSYS2 monorepo build complete.  Binaries in: %DIST%
echo.
echo To run a service, use the generated launcher (prepends MSYS2 bin to PATH):
echo    %DIST%\\run_^<service^>.bat
echo Launching the .exe directly will silently die if any transitive MSYS2
echo DLL — or a Qt platform plugin — isn't reachable.
endlocal
exit /b 0

:emit_launcher
:: %~1 = launcher path, %~2 = target exe name
> "%~1" echo @echo off
>> "%~1" echo if not defined MSYS2_ROOT set "MSYS2_ROOT=C:\\msys64\\mingw64"
>> "%~1" echo set "PATH=%%MSYS2_ROOT%%\\bin;%%PATH%%"
>> "%~1" echo "%%~dp0%~2" %%*
exit /b 0

:emit_gui_launcher
:: Same as :emit_launcher but also exposes Qt plugins.  windeployqt drops
:: `platforms/`, `qml/`, `styles/`, ... next to the exe, so Qt's automatic
:: lookup finds them.  QT_PLUGIN_PATH is a belt-and-braces fallback for
:: when windeployqt wasn't available at build time.
:: %~1 = launcher path, %~2 = target exe name
> "%~1" echo @echo off
>> "%~1" echo if not defined MSYS2_ROOT set "MSYS2_ROOT=C:\\msys64\\mingw64"
>> "%~1" echo set "PATH=%%MSYS2_ROOT%%\\bin;%%PATH%%"
>> "%~1" echo if not defined QT_PLUGIN_PATH set "QT_PLUGIN_PATH=%%MSYS2_ROOT%%\\share\\qt6\\plugins"
>> "%~1" echo if not defined QML2_IMPORT_PATH set "QML2_IMPORT_PATH=%%MSYS2_ROOT%%\\share\\qt6\\qml"
>> "%~1" echo "%%~dp0%~2" %%*
exit /b 0
'''


# ----------------------------------------------------------------------
# Monorepo: client subproject (one test binary per service)
# ----------------------------------------------------------------------

def _mono_client_files(spec, services) -> Dict[str, str]:
    """Client subproject for the monorepo.

    Always emits an interactive console client (``<project>_client``).  If
    ``spec.gui_type`` is ``widget``/``wasm``/``qml``, also emits a matching
    UI client (``<project>_gui``) with service→method pickers and a JSON
    request/response editor.  All UI variants share the same JSON-based
    ``ClientRegistry`` backend so they work uniformly with imported and
    wizard-generated protos.
    """
    sn = spec.snake_name
    ns = spec.proto_namespace
    pkg = spec.proto_package
    project_snake = sn
    files: Dict[str, str] = {}

    # ---- Console client (always) -------------------------------------
    files["client/src/client.cpp"] = _mono_client_main_cpp(spec, services)
    files["client/src/client_common.h"] = _mono_client_common_h()
    for svc in services:
        files[f"client/src/{_mono_snake(svc.name)}_menu.h"]   = _mono_client_menu_h(spec, svc)
        files[f"client/src/{_mono_snake(svc.name)}_menu.cpp"] = _mono_client_menu_cpp(spec, svc)

    # ---- Shared JSON-based dispatch registry (for UI clients) --------
    ui_kind = spec.gui_type if spec.gui_type in ("widget", "wasm", "qml") else "none"
    if ui_kind != "none":
        files["client/gui/ClientRegistry.h"]   = _mono_client_registry_h()
        files["client/gui/ClientRegistry.cpp"] = _mono_client_registry_cpp(spec, services)

    if ui_kind in ("widget", "wasm"):
        files["client/gui/main.cpp"]      = _mono_widget_main_cpp()
        files["client/gui/MainWindow.h"]  = _mono_widget_mainwindow_h()
        files["client/gui/MainWindow.cpp"] = _mono_widget_mainwindow_cpp(spec)
        if ui_kind == "wasm":
            files["client/build_wasm.bat"] = _mono_wasm_build_bat(spec)
            files["client/build_wasm.sh"]  = _mono_wasm_build_sh(spec)
    elif ui_kind == "qml":
        files["client/gui/main.cpp"]         = _mono_qml_main_cpp(spec)
        files["client/gui/ClientBridge.h"]   = _mono_qml_bridge_h()
        files["client/gui/ClientBridge.cpp"] = _mono_qml_bridge_cpp()
        # QML type names come from the file stem and must start uppercase.
        files["client/gui/Main.qml"]         = _mono_qml_main_qml(spec)

    # ---- CMakeLists.txt ----------------------------------------------
    files["client/CMakeLists.txt"] = _mono_client_cmake(spec, services, ui_kind)

    # ---- README ------------------------------------------------------
    svc_list = "\n".join(
        f"- **{s.name}** — {len(s.methods)} RPC method(s)" for s in services
    )
    ui_section = ""
    if ui_kind in ("widget", "wasm"):
        ui_section = f'''
## UI client

A Qt Widgets UI (`{project_snake}_gui`) is also built.  It has the same
service→method picker plus a JSON editor for the request and a read-only
JSON view of the response.  All proto messages are (de)serialised with
`google::protobuf::util::JsonStringToMessage` so it works for both
imported and generated protos without per-field code.
'''
        if ui_kind == "wasm":
            ui_section += f'''
To build the WASM target run `client/build_wasm.bat` (Windows) or
`client/build_wasm.sh` (Linux) — requires the Qt for WebAssembly SDK.
'''
    elif ui_kind == "qml":
        ui_section = f'''
## UI client

A Qt Quick (QML) UI (`{project_snake}_gui`) is also built.  UI logic is
in `gui/main.qml`; the C++ backend `ClientBridge` exposes the JSON
invoke/list helpers from `ClientRegistry` as Q_INVOKABLE methods.
'''

    files["client/README.md"] = f'''# {spec.service_name} client

Single interactive client for the whole **{spec.service_name}**
monorepo.  On launch it shows a menu of services; pick one and it
shows that service's RPC methods; pick one and it's invoked.

## Services

{svc_list}

## Usage (console)

```cmd
:: Consul-based discovery (default)
{project_snake}_client

:: Direct connection (bypass Consul) — applied to every service
{project_snake}_client --direct 127.0.0.1:50051
```
{ui_section}
For methods whose request/response come from an imported .proto, the
console client calls the RPC with a default-constructed request and
prints status only.  Fill in `req.set_<field>(...)` in
`client/src/<svc>_menu.cpp` to exercise real values — or use the JSON
UI (if generated) which handles arbitrary messages via reflection.
'''
    return files


# ----------------------------------------------------------------------
# Monorepo client CMakeLists.txt
# ----------------------------------------------------------------------

def _mono_client_cmake(spec, services, ui_kind: str) -> str:
    sn = spec.snake_name
    project_snake = sn

    console_sources = "\n".join(
        f"    src/{_mono_snake(s.name)}_menu.cpp" for s in services
    )

    gui_block = ""
    if ui_kind in ("widget", "wasm"):
        gui_block = f'''
# ---- UI client ({ui_kind}) ----------------------------------------------
# Qt 6 discovery: honour QT_DIR / Qt6_DIR env vars (set in ../set_env.bat).
if(NOT DEFINED Qt6_DIR AND DEFINED ENV{{Qt6_DIR}})
    set(Qt6_DIR "$ENV{{Qt6_DIR}}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{{QT_DIR}} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{{QT_DIR}}")
endif()

find_package(Qt6 COMPONENTS Core Gui Widgets REQUIRED)
qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)

qt_add_executable({project_snake}_gui
    gui/main.cpp
    gui/MainWindow.cpp
    gui/MainWindow.h
    gui/ClientRegistry.cpp
    gui/ClientRegistry.h
    ${{STUB_SRCS}})

target_include_directories({project_snake}_gui PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/gui"
    "${{PROTO_DIR}}")

target_link_libraries({project_snake}_gui PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
    Qt6::Widgets)

set_target_properties({project_snake}_gui PROPERTIES
    WIN32_EXECUTABLE ON
    MACOSX_BUNDLE    ON)
'''
    elif ui_kind == "qml":
        gui_block = f'''
# ---- UI client (qml) ---------------------------------------------------
if(NOT DEFINED Qt6_DIR AND DEFINED ENV{{Qt6_DIR}})
    set(Qt6_DIR "$ENV{{Qt6_DIR}}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{{QT_DIR}} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{{QT_DIR}}")
endif()

find_package(Qt6 COMPONENTS Core Gui Quick Qml REQUIRED)
qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)

qt_add_executable({project_snake}_gui
    gui/main.cpp
    gui/ClientBridge.cpp
    gui/ClientBridge.h
    gui/ClientRegistry.cpp
    gui/ClientRegistry.h
    ${{STUB_SRCS}})

qt_add_qml_module({project_snake}_gui
    URI {project_snake}
    VERSION 1.0
    QML_FILES gui/Main.qml)

target_include_directories({project_snake}_gui PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/gui"
    "${{PROTO_DIR}}")

target_link_libraries({project_snake}_gui PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
    Qt6::Quick
    Qt6::Qml)
'''

    return f'''cmake_minimum_required(VERSION 3.16)
project({spec.service_name}Client VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain")
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

add_subdirectory(
    "${{CMAKE_CURRENT_SOURCE_DIR}}/../../../MicroserviceBase/runtime_cpp"
    "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")

# Shared proto stubs from the parent project's proto/ folder.
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/../proto")
set(STUB_SRCS
    "${{PROTO_DIR}}/{sn}.pb.cc"
    "${{PROTO_DIR}}/{sn}.grpc.pb.cc")

if(NOT EXISTS "${{PROTO_DIR}}/{sn}.pb.h")
    message(FATAL_ERROR
        "Proto stubs not found in ${{PROTO_DIR}}.\\n"
        "Run proto/generate_stubs.bat (Win) or .sh (Linux) first.")
endif()

# ---- Console client ----------------------------------------------------
add_executable({project_snake}_client
    src/client.cpp
{console_sources}
    ${{STUB_SRCS}})

target_include_directories({project_snake}_client PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{PROTO_DIR}}")

target_link_libraries({project_snake}_client PRIVATE
    microservice_base::runtime
    gRPC::grpc++ protobuf::libprotobuf)
{gui_block}'''


# ----------------------------------------------------------------------
# Monorepo: shared JSON-based dispatch registry
# ----------------------------------------------------------------------

def _mono_client_registry_h() -> str:
    return '''#pragma once

// Shared JSON-based dispatch registry used by every UI client variant.
//
// Each (service, method) pair parses the request as JSON via
// google::protobuf::util::JsonStringToMessage, invokes the RPC, then
// serialises the response back to JSON.  Works for arbitrary imported
// protos without per-field code.

#include <string>
#include <utility>
#include <vector>

namespace client_registry {

/// Set the direct host:port for every subsequent invoke().  Pass an empty
/// string to use Consul (default).  Changing it resets all cached clients.
void set_direct_host(const std::string& hostPort);

/// List the services available in this monorepo.
std::vector<std::string> services();

/// List the RPC methods defined by the given service.  Returns an empty
/// vector if the service name is unknown.
std::vector<std::string> methods(const std::string& serviceName);

/// Invoke an RPC with a JSON-encoded request.  Returns {ok, jsonOrError}.
///  - On success: .first = true, .second = response as JSON.
///  - On failure: .first = false, .second = human-readable error message.
std::pair<bool, std::string>
invoke(const std::string& serviceName,
       const std::string& methodName,
       const std::string& requestJson);

}  // namespace client_registry
'''


def _mono_client_registry_cpp(spec, services) -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace

    # Client slots (one unique_ptr per service) + lazy getters.
    client_slots = []
    getter_fns = []
    for svc in services:
        svc_pascal = svc.name
        svc_snake = _mono_snake(svc.name)
        client_slots.append(
            f'    std::unique_ptr<microservice_base::ServiceClient<{ns}::{svc_pascal}>> '
            f'g_{svc_snake}_client;')
        getter_fns.append(f'''    microservice_base::ServiceClient<{ns}::{svc_pascal}>&
    get_{svc_snake}_client() {{
        if (!g_{svc_snake}_client) {{
            if (!g_direct_host.empty())
                g_{svc_snake}_client = std::make_unique<
                    microservice_base::ServiceClient<{ns}::{svc_pascal}>>(
                        "{svc_snake}", g_direct_host, true);
            else
                g_{svc_snake}_client = std::make_unique<
                    microservice_base::ServiceClient<{ns}::{svc_pascal}>>(
                        "{svc_snake}");
        }}
        return *g_{svc_snake}_client;
    }}''')

    svc_labels = ", ".join(f'"{s.name}"' for s in services)

    # methods(service) dispatch
    methods_cases = []
    for svc in services:
        method_labels = ", ".join(f'"{m.name}"' for m in svc.methods)
        methods_cases.append(
            f'    if (serviceName == "{svc.name}") return {{ {method_labels} }};')
    methods_body = "\n".join(methods_cases) if methods_cases else "    (void)serviceName;"

    # invoke(service, method, json) dispatch
    invoke_cases = []
    for svc in services:
        svc_pascal = svc.name
        svc_snake = _mono_snake(svc.name)
        for m in svc.methods:
            inT  = _mono_input_cpp_type(m, ns)
            outT = _mono_output_cpp_type(m, ns)
            if m.server_streaming:
                body = f'''    if (serviceName == "{svc.name}" && methodName == "{m.name}") {{
        return {{ false, "{m.name}: streaming RPCs are not supported by the JSON UI client." }};
    }}'''
            else:
                body = f'''    if (serviceName == "{svc.name}" && methodName == "{m.name}") {{
        {inT} req;
        auto s0 = google::protobuf::util::JsonStringToMessage(requestJson, &req);
        if (!s0.ok()) return {{ false, std::string("JSON parse: ") + s0.ToString() }};
        {outT} resp;
        grpc::ClientContext ctx;
        grpc::Status st;
        try {{
            auto& c = get_{svc_snake}_client();
            st = c.stub().{m.name}(&ctx, req, &resp);
        }} catch (const std::exception& e) {{
            return {{ false, std::string("Connect failed: ") + e.what() }};
        }}
        if (!st.ok()) return {{ false, std::string("RPC failed: ") + st.error_message() }};
        std::string out;
        google::protobuf::util::JsonPrintOptions opts;
        opts.add_whitespace = true;
        auto s1 = google::protobuf::util::MessageToJsonString(resp, &out, opts);
        if (!s1.ok()) return {{ false, std::string("JSON serialize: ") + s1.ToString() }};
        return {{ true, out }};
    }}'''
            invoke_cases.append(body)

    invoke_body = "\n".join(invoke_cases)

    reset_stmts = "\n".join(
        f"    g_{_mono_snake(s.name)}_client.reset();" for s in services
    )

    return f'''#include "ClientRegistry.h"

#include <grpcpp/grpcpp.h>
#include <google/protobuf/util/json_util.h>

#include <memory>

#include "{sn}.grpc.pb.h"
#include "MicroserviceBase/ServiceClient.h"

namespace client_registry {{
namespace {{

std::string g_direct_host;

{chr(10).join(client_slots)}

{chr(10).join(getter_fns)}

}}  // anonymous

void set_direct_host(const std::string& hostPort) {{
    if (hostPort == g_direct_host) return;
    g_direct_host = hostPort;
{reset_stmts}
}}

std::vector<std::string> services() {{
    return {{ {svc_labels} }};
}}

std::vector<std::string> methods(const std::string& serviceName) {{
{methods_body}
    return {{}};
}}

std::pair<bool, std::string>
invoke(const std::string& serviceName,
       const std::string& methodName,
       const std::string& requestJson) {{
{invoke_body}
    return {{ false, "Unknown (service, method) pair: " + serviceName + "." + methodName }};
}}

}}  // namespace client_registry
'''


# ----------------------------------------------------------------------
# Monorepo: Qt Widgets UI client
# ----------------------------------------------------------------------

def _mono_widget_main_cpp() -> str:
    return '''#include <QApplication>
#include "MainWindow.h"

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);
    MainWindow w;
    w.show();
    return app.exec();
}
'''


def _mono_widget_mainwindow_h() -> str:
    return '''#pragma once

#include <QWidget>

QT_BEGIN_NAMESPACE
class QComboBox;
class QTextEdit;
class QLineEdit;
class QCheckBox;
class QPushButton;
class QLabel;
QT_END_NAMESPACE

class MainWindow : public QWidget {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);

private slots:
    void onServiceChanged(int);
    void onSend();
    void onConsulToggled(bool consul);

private:
    void applyHostMode();

    QLineEdit*   m_directHost = nullptr;
    QCheckBox*   m_useConsul  = nullptr;
    QComboBox*   m_serviceCombo = nullptr;
    QComboBox*   m_methodCombo  = nullptr;
    QTextEdit*   m_requestEdit  = nullptr;
    QTextEdit*   m_responseEdit = nullptr;
    QPushButton* m_sendButton   = nullptr;
    QLabel*      m_statusLabel  = nullptr;
};
'''


def _mono_widget_mainwindow_cpp(spec) -> str:
    title = f"{spec.service_name} Client"
    return f'''#include "MainWindow.h"
#include "ClientRegistry.h"

#include <QCheckBox>
#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QTextEdit>
#include <QVBoxLayout>

MainWindow::MainWindow(QWidget* parent) : QWidget(parent) {{
    setWindowTitle("{title}");
    resize(820, 640);

    auto* v = new QVBoxLayout(this);

    // ---- Host row ----
    auto* hostRow = new QHBoxLayout;
    m_useConsul  = new QCheckBox("Use Consul", this);
    m_useConsul->setChecked(true);
    m_directHost = new QLineEdit(this);
    m_directHost->setPlaceholderText("host:port (when Consul disabled)");
    m_directHost->setEnabled(false);
    hostRow->addWidget(m_useConsul);
    hostRow->addWidget(m_directHost, 1);
    v->addLayout(hostRow);

    // ---- Service + method row ----
    auto* pickRow = new QHBoxLayout;
    pickRow->addWidget(new QLabel("Service:", this));
    m_serviceCombo = new QComboBox(this);
    pickRow->addWidget(m_serviceCombo, 1);
    pickRow->addWidget(new QLabel("Method:", this));
    m_methodCombo = new QComboBox(this);
    pickRow->addWidget(m_methodCombo, 1);
    v->addLayout(pickRow);

    // ---- Request JSON ----
    v->addWidget(new QLabel("Request (JSON):", this));
    m_requestEdit = new QTextEdit(this);
    m_requestEdit->setPlainText("{{}}");
    v->addWidget(m_requestEdit, 1);

    // ---- Send + status ----
    auto* sendRow = new QHBoxLayout;
    m_sendButton = new QPushButton("Send", this);
    m_statusLabel = new QLabel("(idle)", this);
    sendRow->addWidget(m_sendButton);
    sendRow->addWidget(m_statusLabel, 1);
    v->addLayout(sendRow);

    // ---- Response JSON ----
    v->addWidget(new QLabel("Response:", this));
    m_responseEdit = new QTextEdit(this);
    m_responseEdit->setReadOnly(true);
    v->addWidget(m_responseEdit, 2);

    // ---- Populate services ----
    for (const auto& s : client_registry::services())
        m_serviceCombo->addItem(QString::fromStdString(s));
    onServiceChanged(0);

    connect(m_serviceCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWindow::onServiceChanged);
    connect(m_sendButton, &QPushButton::clicked, this, &MainWindow::onSend);
    connect(m_useConsul, &QCheckBox::toggled, this, &MainWindow::onConsulToggled);
    connect(m_directHost, &QLineEdit::editingFinished, this,
            [this]() {{ applyHostMode(); }});

    applyHostMode();
}}

void MainWindow::onConsulToggled(bool consul) {{
    m_directHost->setEnabled(!consul);
    applyHostMode();
}}

void MainWindow::applyHostMode() {{
    if (m_useConsul->isChecked())
        client_registry::set_direct_host("");
    else
        client_registry::set_direct_host(m_directHost->text().toStdString());
}}

void MainWindow::onServiceChanged(int) {{
    m_methodCombo->clear();
    auto svc = m_serviceCombo->currentText().toStdString();
    for (const auto& m : client_registry::methods(svc))
        m_methodCombo->addItem(QString::fromStdString(m));
}}

void MainWindow::onSend() {{
    auto svc = m_serviceCombo->currentText().toStdString();
    auto mth = m_methodCombo->currentText().toStdString();
    if (svc.empty() || mth.empty()) {{
        m_statusLabel->setText("Pick a service and method first.");
        return;
    }}
    auto req = m_requestEdit->toPlainText().toStdString();
    m_statusLabel->setText(QString("Calling %1.%2 ...")
        .arg(QString::fromStdString(svc), QString::fromStdString(mth)));
    auto [ok, body] = client_registry::invoke(svc, mth, req);
    m_responseEdit->setPlainText(QString::fromStdString(body));
    m_statusLabel->setText(ok ? "OK" : "FAILED");
}}
'''


# ----------------------------------------------------------------------
# Monorepo: WASM build scripts (reuses the Widget client)
# ----------------------------------------------------------------------

def _mono_wasm_build_bat(spec) -> str:
    project_snake = spec.snake_name
    return f'''@echo off
:: Build the Qt Widgets monorepo client ({project_snake}_gui) as WebAssembly.
:: Requires:
::   - Qt for WebAssembly (QT_WASM_DIR env var pointing at the install)
::   - Emscripten SDK (EMSDK env var)  — run emsdk_env.bat first
::
:: Output: client/build-wasm/{project_snake}_gui.{{html,js,wasm}}

setlocal
if not defined QT_WASM_DIR (
    echo ERROR: QT_WASM_DIR not set ^(path to Qt-for-WebAssembly install^).
    exit /b 1
)
if not defined EMSDK (
    echo ERROR: EMSDK not set.  Run emsdk_env.bat before this script.
    exit /b 1
)

set "BUILD=%~dp0build-wasm"
if not exist "%BUILD%" mkdir "%BUILD%"
cd /d "%BUILD%"

"%QT_WASM_DIR%\\bin\\qt-cmake.bat" -G Ninja .. ^
    -DCMAKE_BUILD_TYPE=Release

cmake --build . --target {project_snake}_gui
if errorlevel 1 exit /b 1

echo WASM client built: %BUILD%\\{project_snake}_gui.html
endlocal
'''


def _mono_wasm_build_sh(spec) -> str:
    project_snake = spec.snake_name
    return f'''#!/usr/bin/env bash
# Build the Qt Widgets monorepo client ({project_snake}_gui) as WebAssembly.
#
# Requires Qt for WebAssembly (QT_WASM_DIR) + Emscripten (source emsdk_env.sh).

set -euo pipefail

: "${{QT_WASM_DIR:?Set QT_WASM_DIR to your Qt-for-WebAssembly install}}"
: "${{EMSDK:?Run emsdk_env.sh before this script}}"

BUILD="$(dirname "$(readlink -f "$0")")/build-wasm"
mkdir -p "$BUILD"
cd "$BUILD"

"$QT_WASM_DIR/bin/qt-cmake" -G Ninja .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --target {project_snake}_gui

echo "WASM client built: $BUILD/{project_snake}_gui.html"
'''


# ----------------------------------------------------------------------
# Monorepo: Qt Quick (QML) UI client
# ----------------------------------------------------------------------

def _mono_qml_main_cpp(spec) -> str:
    project_snake = spec.snake_name
    return f'''#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>

#include "ClientBridge.h"

int main(int argc, char* argv[]) {{
    QGuiApplication app(argc, argv);
    QQmlApplicationEngine engine;

    ClientBridge bridge;
    engine.rootContext()->setContextProperty("clientBridge", &bridge);

    // URI must match qt_add_qml_module(... URI {project_snake} ...) in CMake.
    engine.loadFromModule("{project_snake}", "Main");
    if (engine.rootObjects().isEmpty()) return 1;
    return app.exec();
}}
'''


def _mono_qml_bridge_h() -> str:
    return '''#pragma once

// Qt/QML-facing wrapper around ClientRegistry.  All methods are
// Q_INVOKABLE so QML can call them directly as `clientBridge.*`.

#include <QObject>
#include <QString>
#include <QStringList>
#include <QVariantMap>

class ClientBridge : public QObject {
    Q_OBJECT
public:
    explicit ClientBridge(QObject* parent = nullptr) : QObject(parent) {}

    Q_INVOKABLE QStringList services() const;
    Q_INVOKABLE QStringList methods(const QString& serviceName) const;

    Q_INVOKABLE void setDirectHost(const QString& hostPort);

    /// Returns { "ok": bool, "body": QString }.
    Q_INVOKABLE QVariantMap invoke(const QString& serviceName,
                                   const QString& methodName,
                                   const QString& requestJson);
};
'''


def _mono_qml_bridge_cpp() -> str:
    return '''#include "ClientBridge.h"
#include "ClientRegistry.h"

QStringList ClientBridge::services() const {
    QStringList out;
    for (const auto& s : client_registry::services())
        out << QString::fromStdString(s);
    return out;
}

QStringList ClientBridge::methods(const QString& serviceName) const {
    QStringList out;
    for (const auto& m : client_registry::methods(serviceName.toStdString()))
        out << QString::fromStdString(m);
    return out;
}

void ClientBridge::setDirectHost(const QString& hostPort) {
    client_registry::set_direct_host(hostPort.toStdString());
}

QVariantMap ClientBridge::invoke(const QString& serviceName,
                                 const QString& methodName,
                                 const QString& requestJson) {
    auto [ok, body] = client_registry::invoke(
        serviceName.toStdString(),
        methodName.toStdString(),
        requestJson.toStdString());
    QVariantMap m;
    m["ok"] = ok;
    m["body"] = QString::fromStdString(body);
    return m;
}
'''


def _mono_qml_main_qml(spec) -> str:
    title = f"{spec.service_name} Client"
    return f'''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {{
    width: 820; height: 640
    visible: true
    title: "{title}"

    ColumnLayout {{
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        RowLayout {{
            CheckBox {{
                id: useConsul
                text: "Use Consul"
                checked: true
                onCheckedChanged: {{
                    if (checked) clientBridge.setDirectHost("")
                    else         clientBridge.setDirectHost(directHost.text)
                }}
            }}
            TextField {{
                id: directHost
                enabled: !useConsul.checked
                placeholderText: "host:port (when Consul disabled)"
                Layout.fillWidth: true
                onEditingFinished: if (!useConsul.checked)
                    clientBridge.setDirectHost(text)
            }}
        }}

        RowLayout {{
            Label {{ text: "Service:" }}
            ComboBox {{
                id: svcCombo
                model: clientBridge.services()
                Layout.fillWidth: true
                onCurrentTextChanged: methodCombo.model =
                    clientBridge.methods(currentText)
                Component.onCompleted: methodCombo.model =
                    clientBridge.methods(currentText)
            }}
            Label {{ text: "Method:" }}
            ComboBox {{
                id: methodCombo
                Layout.fillWidth: true
            }}
        }}

        Label {{ text: "Request (JSON):" }}
        ScrollView {{
            Layout.fillWidth: true
            Layout.preferredHeight: 140
            TextArea {{
                id: requestEdit
                text: "{{}}"
                wrapMode: TextEdit.Wrap
                font.family: "monospace"
            }}
        }}

        RowLayout {{
            Button {{
                text: "Send"
                onClicked: {{
                    statusLabel.text = "Calling " + svcCombo.currentText +
                        "." + methodCombo.currentText + " ..."
                    var r = clientBridge.invoke(svcCombo.currentText,
                                                methodCombo.currentText,
                                                requestEdit.text)
                    responseEdit.text = r.body
                    statusLabel.text = r.ok ? "OK" : "FAILED"
                }}
            }}
            Label {{
                id: statusLabel
                text: "(idle)"
                Layout.fillWidth: true
            }}
        }}

        Label {{ text: "Response:" }}
        ScrollView {{
            Layout.fillWidth: true
            Layout.fillHeight: true
            TextArea {{
                id: responseEdit
                readOnly: true
                wrapMode: TextEdit.Wrap
                font.family: "monospace"
            }}
        }}
    }}
}}
'''


def _mono_client_common_h() -> str:
    return '''#pragma once

// Shared helpers for the unified monorepo client.

#include <string>
#include <vector>

namespace client_common {

// Optional "host:port" for --direct mode.  Empty = use Consul.
extern std::string g_direct_host;

// Render a numbered menu and read one choice.  Returns 0 on "back/quit"
// or invalid input, 1..choices.size() on a valid pick.
int prompt_choice(const std::string& title,
                  const std::vector<std::string>& choices);

}  // namespace client_common
'''


def _mono_client_main_cpp(spec, services) -> str:
    sn = spec.snake_name
    project_snake = sn

    includes = "\n".join(
        f'#include "{_mono_snake(s.name)}_menu.h"' for s in services
    )

    labels = ", ".join(f'"{s.name}"' for s in services)

    dispatch_cases = "\n".join(
        f"            case {i+1}: {_mono_snake(s.name)}_menu::run(); break;"
        for i, s in enumerate(services)
    )

    return f'''// client.cpp — unified interactive test client for the
// {spec.service_name} monorepo.  Picks a service, then an RPC method.

#include <iostream>
#include <string>
#include <vector>
#include "client_common.h"
{includes}

namespace client_common {{
    std::string g_direct_host;

    int prompt_choice(const std::string& title,
                      const std::vector<std::string>& choices) {{
        std::cout << "\\n" << title << "\\n";
        for (size_t i = 0; i < choices.size(); ++i)
            std::cout << "  " << (i + 1) << ") " << choices[i] << "\\n";
        std::cout << "  0) back/quit\\n> " << std::flush;
        int sel = 0;
        if (!(std::cin >> sel)) {{
            std::cin.clear();
            std::string discard; std::cin >> discard;
            return 0;
        }}
        if (sel < 0 || sel > static_cast<int>(choices.size())) return 0;
        return sel;
    }}
}}

int main(int argc, char* argv[]) {{
    for (int i = 1; i < argc; ++i) {{
        std::string a = argv[i];
        if (a == "--direct" && i + 1 < argc) {{
            client_common::g_direct_host = argv[++i];
        }} else if (a == "-h" || a == "--help") {{
            std::cout <<
                "Usage: {project_snake}_client [--direct host:port]\\n"
                "  --direct  bypass Consul, use <host:port> for every service\\n";
            return 0;
        }}
    }}

    if (!client_common::g_direct_host.empty()) {{
        std::cout << "Direct mode -> " << client_common::g_direct_host << "\\n";
    }} else {{
        std::cout << "Consul discovery mode\\n";
    }}

    std::vector<std::string> svc_labels = {{ {labels} }};
    while (true) {{
        int pick = client_common::prompt_choice("Pick a service:", svc_labels);
        if (pick == 0) break;
        switch (pick) {{
{dispatch_cases}
            default: break;
        }}
    }}
    return 0;
}}
'''


def _mono_client_menu_h(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    return f'''#pragma once

// Interactive method menu for {svc.name}.

namespace {svc_snake}_menu {{
    void run();
}}
'''


def _mono_client_menu_cpp(spec, svc) -> str:
    """Interactive per-service menu: resolves the stub, then loops showing
    a list of RPC methods.  Each method is invoked with a default request
    (for imported protos) or sample values (for wizard-generated protos)."""
    sn = spec.snake_name
    ns = spec.proto_namespace
    svc_pascal = svc.name
    svc_snake = _mono_snake(svc.name)

    method_labels = ", ".join(f'"{m.name}"' for m in svc.methods)

    # Build one `case N:` block per method.
    cases = []
    for idx, m in enumerate(svc.methods, start=1):
        inT  = _mono_input_cpp_type(m, ns)
        outT = _mono_output_cpp_type(m, ns)
        imported = bool(m.input_type or m.output_type)

        if imported:
            body = f'''            case {idx}: {{
                grpc::ClientContext ctx;
                {inT} req;   // TODO: fill fields — set_<field>(...)
                {outT} resp;
                auto st = stub.{m.name}(&ctx, req, &resp);
                if (st.ok()) std::cout << "  {m.name}: OK (fill in response print)\\n";
                else         std::cerr << "  {m.name} FAILED: " << st.error_message() << "\\n";
                break;
            }}'''
            cases.append(body)
            continue

        # Wizard-generated conventions: parameters map to set_<param>().
        param_lines = []
        for p in m.params:
            t = (p.type or "string").lower()
            if t in ("string", "bytes", "str"):
                param_lines.append(f'                req.set_{p.name}("sample");')
            elif t in ("int32", "int", "uint32", "int64", "uint64"):
                param_lines.append(f'                req.set_{p.name}(1);')
            elif t in ("float", "double"):
                param_lines.append(f'                req.set_{p.name}(1.0);')
            elif t == "bool":
                param_lines.append(f'                req.set_{p.name}(true);')
            else:
                param_lines.append(f'                req.set_{p.name}("sample");')
        setters = "\n".join(param_lines) if param_lines else "                // no params"

        rt = (m.return_type or "string").lower()
        if rt == "bool":
            print_expr = '(resp.result() ? "true" : "false")'
        else:
            print_expr = "resp.result()"

        if m.server_streaming:
            body = f'''            case {idx}: {{
                grpc::ClientContext ctx;
                {inT} req;
{setters}
                auto reader = stub.{m.name}(&ctx, req);
                {outT} resp;
                int n = 0;
                while (reader->Read(&resp)) {{
                    std::cout << "  {m.name} [" << n++ << "] = " << {print_expr} << "\\n";
                }}
                auto st = reader->Finish();
                std::cout << "  {m.name}: " << (st.ok() ? "done" : st.error_message()) << "\\n";
                break;
            }}'''
        else:
            body = f'''            case {idx}: {{
                grpc::ClientContext ctx;
                {inT} req;
{setters}
                {outT} resp;
                auto st = stub.{m.name}(&ctx, req, &resp);
                if (st.ok()) std::cout << "  {m.name} -> " << {print_expr} << "\\n";
                else         std::cerr << "  {m.name} FAILED: " << st.error_message() << "\\n";
                break;
            }}'''
        cases.append(body)

    cases_joined = "\n".join(cases) if cases \
        else '            default: std::cout << "(no methods)\\n"; break;'

    return f'''// {svc_pascal} interactive test menu.
//
// Each entry invokes one RPC on a persistent ServiceClient<{svc_pascal}>
// (opened on first use, reused while this menu is active).

#include <iostream>
#include <memory>
#include <string>
#include <vector>
#include <grpcpp/grpcpp.h>
#include "{sn}.grpc.pb.h"
#include "MicroserviceBase/ServiceClient.h"
#include "client_common.h"
#include "{svc_snake}_menu.h"

using {ns}::{svc_pascal};

namespace {svc_snake}_menu {{

static std::unique_ptr<microservice_base::ServiceClient<{svc_pascal}>> s_client;

static bool ensure_client() {{
    if (s_client) return true;
    try {{
        if (!client_common::g_direct_host.empty()) {{
            s_client = std::make_unique<microservice_base::ServiceClient<{svc_pascal}>>(
                "{svc_snake}", client_common::g_direct_host, true);
            std::cout << "{svc_pascal}: connected direct -> "
                      << s_client->target() << "\\n";
        }} else {{
            s_client = std::make_unique<microservice_base::ServiceClient<{svc_pascal}>>(
                "{svc_snake}");
            std::cout << "{svc_pascal}: resolved via Consul -> "
                      << s_client->target() << "\\n";
        }}
    }} catch (const std::exception& e) {{
        std::cerr << "{svc_pascal}: connect failed: " << e.what() << "\\n";
        s_client.reset();
        return false;
    }}
    return true;
}}

void run() {{
    if (!ensure_client()) return;
    auto& stub = s_client->stub();

    std::vector<std::string> labels = {{ {method_labels} }};
    while (true) {{
        int pick = client_common::prompt_choice(
            "{svc_pascal} — pick a method:", labels);
        if (pick == 0) return;
        switch (pick) {{
{cases_joined}
            default: break;
        }}
    }}
}}

}}  // namespace {svc_snake}_menu
'''


