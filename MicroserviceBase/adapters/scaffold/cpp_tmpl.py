"""C++ service scaffold templates.

Generates CMake-based projects for gRPC microservices using the
MicroserviceBase C++ runtime (ServiceRunner + ConsulRegistration).
Supports four GUI variants: none, qml, wasm, widget.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict

from .shared import cpp_file_header

if TYPE_CHECKING:
    from .generator import ScaffoldSpec


# Reusable CMake function emitted into every top-level CMakeLists.txt.
# Copies vcpkg DLLs + MinGW runtime + (optionally) windeployqt output
# next to each .exe on every successful build, so Qt Creator F5 / Run
# works without manual PATH or pre-running deploy_qt_vcpkg.bat.
# Disable per-build with -DMB_DEPLOY_RUNTIME_DEPS=OFF.
# This is a Python-level constant interpolated as `{_MB_DEPLOY_RUNTIME_BLOCK}`
# inside f-string templates -- the f-string substitutes the literal text
# without re-formatting it, so single-brace CMake syntax stays intact.
_MB_DEPLOY_RUNTIME_BLOCK = '''# ---- Auto-deploy runtime DLLs (POST_BUILD) ----
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
'''


def generate(spec: "ScaffoldSpec") -> Dict[str, str]:
    """
Render every file for a C++ gRPC service scaffold.

Produces a fully buildable project tree: CMakeLists, ``main.cpp``,
``Settings.h``, domain stubs, gRPC adapter, env-var scripts
(``set_env.bat`` / ``.sh`` / MinGW / MSYS2 / MSVC variants), build
scripts (``build_deploy*.bat``), proto-stub generator scripts, and
optionally Qt UI files (QML / WASM / Widget) per ``spec.gui_type``.

Internal ``_xxx`` helpers in this module each return one file's text
verbatim — they are not meant to be called directly; ``generate`` is
the single public entry point.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification (service name, methods, GUI type, client /
  server gRPC kind, toolchain hints, …).

**Returns:**

* ``files``

  / *Type*: Dict[str, str] /

  Map of relative-path-string → file-contents-string for every file
  the scaffold should write.  The caller (``adapters/scaffold/generator.py``)
  writes them to ``output_path/service_name/`` or zips them for
  download.
    """
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

    # GUI files inside client/gui/ — only when client_grpc_kind == "google".
    # The "qt" and "google_vcpkg" variants emit standalone Qt projects below
    # (qt_client/ and qt_client_grpcpp/) so the client uses the Qt-installer
    # MinGW toolchain with no ABI conflict against the server.
    google_gui = spec.gui_type != "none" and spec.client_grpc_kind == "google"
    if google_gui and spec.gui_type == "qml":
        files.update(_qml_files(spec))
    elif google_gui and spec.gui_type == "wasm":
        files.update(_wasm_files(spec))
        if spec.gen_build_scripts:
            files["build_wasm.bat"] = _build_wasm_bat(spec)
            files["build_wasm.sh"] = _build_wasm_sh(spec)
    elif google_gui and spec.gui_type == "widget":
        files.update(_widget_files(spec))

    # ---- Client subproject (Google grpc console + optional GUI) ----
    files.update(_client_files(spec))

    # ---- Optional Qt-native client in qt_client/ (Qt6::Grpc) ----
    if spec.gui_type != "none" and spec.client_grpc_kind == "qt":
        files.update(_qt_client_files(spec, services=None))

    # ---- Optional Qt-native client in qt_client_grpcpp/ (Google grpc++ via vcpkg) ----
    client_uses_vcpkg = (spec.gui_type != "none"
                        and spec.client_grpc_kind == "google_vcpkg")
    if client_uses_vcpkg:
        files.update(_qt_client_grpcpp_files(spec, services=None))

    # ---- Server vcpkg path (Google grpc++ via vcpkg + Qt MinGW) ----
    # Independent of client choice; user can pick "vcpkg" server with
    # any client (qt6::Grpc, MSYS2 grpc++, or vcpkg grpc++).  Wire format
    # is the same.
    server_uses_vcpkg = spec.server_grpc_kind == "vcpkg"
    if server_uses_vcpkg:
        # vcpkg manifest at project root so `cmake configure` (or our
        # explicit `vcpkg install` step) knows what to install.  Same
        # deps as the client: grpc + protobuf + curl (for Consul).
        files["vcpkg.json"] = _server_vcpkg_json(spec)
        if spec.gen_build_scripts:
            files["build_qt_vcpkg.bat"] = _server_build_qt_vcpkg_bat(spec)
            files["deploy_qt_vcpkg.bat"] = _server_deploy_qt_vcpkg_bat(spec)
            # Per-client deploy script (console + Qt Widgets GUI both link
            # against the same vcpkg DLLs as the server).  Only meaningful
            # when client/ is emitted (i.e. when client_grpc_kind == "google"
            # so the client/ Google-grpc subproject exists).
            if spec.gui_type != "none" and spec.client_grpc_kind == "google":
                files["client/deploy_qt_vcpkg.bat"] = _client_deploy_qt_vcpkg_bat(spec)

    # ---- Shared vcpkg infrastructure (triplets/ + ports/ + init script) ----
    # Emit once if EITHER side uses vcpkg.  Both sides can share the
    # same triplet, overlay-port, and binary cache so picking "vcpkg"
    # for both sides means second build is essentially free.
    if client_uses_vcpkg or server_uses_vcpkg:
        files.update(_vcpkg_shared_files(spec))

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

    # Tolerant lookup: vcpkg's grpc port built without the `codegen`
    # feature does NOT define gRPC::grpc_cpp_plugin.  Fall back to
    # find_program against the host-tools dir (x64-windows/tools).
    if(TARGET protobuf::protoc)
        get_target_property(_protoc protobuf::protoc LOCATION)
    else()
        find_program(_protoc NAMES protoc protoc.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/protobuf"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf"
            REQUIRED)
    endif()
    if(TARGET gRPC::grpc_cpp_plugin)
        get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin LOCATION)
    else()
        find_program(_grpc_cpp NAMES grpc_cpp_plugin grpc_cpp_plugin.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/grpc"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/grpc"
            REQUIRED)
    endif()

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
    ${{GRPC_REFL_LIB}}
    protobuf::libprotobuf
)
mb_deploy_runtime({sn})'''

    return f'''cmake_minimum_required(VERSION 3.16)

# ---------------------------------------------------------------------------
# vcpkg auto-detection - MUST run BEFORE project() so the toolchain file
# is loaded in the right phase.  This makes Qt Creator's kit-based build
# work without needing CMakePresets.json or extra Initial Configuration.
# ---------------------------------------------------------------------------
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
    message(STATUS "{svc}: auto-set CMAKE_TOOLCHAIN_FILE = ${{CMAKE_TOOLCHAIN_FILE}}")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "{svc}: VCPKG_ROOT env var not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.  Set VCPKG_ROOT (system or Qt Creator's "
        "Build Environment) or pass -DCMAKE_TOOLCHAIN_FILE=... directly.")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (auto-set from triplets/ overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/triplets"
            CACHE PATH "vcpkg overlay triplets directory")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/ports"
            CACHE PATH "vcpkg overlay ports directory")
    endif()
endif()
if(NOT DEFINED QT_CREATOR_SKIP_VCPKG_SETUP)
    set(QT_CREATOR_SKIP_VCPKG_SETUP ON CACHE BOOL "")
endif()

# Ninja path auto-detect - vcpkg's bundled cmake doesn't always find Ninja
# even when Qt's Ninja is installed.
if(NOT CMAKE_MAKE_PROGRAM)
    set(_ninja_candidates "C:/Qt/Tools/Ninja/ninja.exe" "C:/Qt/Tools/Ninja_64/ninja.exe")
    if(DEFINED ENV{{VCPKG_ROOT}})
        file(GLOB _vcpkg_ninja "$ENV{{VCPKG_ROOT}}/downloads/tools/ninja-*/ninja.exe")
        list(APPEND _ninja_candidates ${{_vcpkg_ninja}})
    endif()
    foreach(_n IN LISTS _ninja_candidates)
        if(EXISTS "${{_n}}")
            set(CMAKE_MAKE_PROGRAM "${{_n}}" CACHE FILEPATH "Ninja (auto-detected)")
            break()
        endif()
    endforeach()
endif()

project({svc} VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# NOTE: don't add the classic-mode x64-windows install dir to
# CMAKE_PREFIX_PATH here.  When vcpkg has packages installed for both
# x64-windows (MSVC-built .lib) and our custom x64-mingw-qt (MinGW .a),
# find_package can resolve to x64-windows first - the MinGW linker then
# chokes on MSVC-style flags like `-ignore:4221`.

# Manifest-mode fallback: when vcpkg toolchain didn't load (no
# CMAKE_TOOLCHAIN_FILE) but the build dir has a populated
# vcpkg_installed/x64-mingw-qt/ (e.g. from import_prebuilt.bat with
# VCPKG_MANIFEST_INSTALL=OFF), point find_package at it directly.
if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()

# Pre-set Protobuf_PROTOC_EXECUTABLE so vcpkg's protobuf-cmake-wrapper
# (which hardcodes a search at .../x64-windows/tools/protobuf/) doesn't
# fail when only x64-mingw-qt's tree is present.  Both protoc binaries
# are equivalent.
if(NOT Protobuf_PROTOC_EXECUTABLE AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc (target triplet)")
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# gRPC server reflection - both supported toolchains ship it (MSYS2's
# stock grpc; our vcpkg overlay-port which forces gRPC_BUILD_CODEGEN=ON).
# Kept as a guard for unusual grpc distributions that omit it; the
# Manager GUI also has a LocalProtoClient fallback as a safety net.
if(TARGET gRPC::grpc++_reflection)
    set(GRPC_REFL_LIB gRPC::grpc++_reflection)
else()
    set(GRPC_REFL_LIB "")
endif()

# MicroserviceBase C++ runtime — three resolution paths:
#   1. find_package() via CMake install or vcpkg overlay-port
#      (also picks up MicroserviceBase_ROOT env var natively)
#   2. MICROSERVICEBASE_DIR env var pointing at a framework checkout —
#      lets you set the path once (setx MICROSERVICEBASE_DIR <path>)
#      and use this scaffold from any directory.  Accepts the
#      framework root, the runtime_cpp parent, or runtime_cpp itself.
#   3. ../../MicroserviceBase/runtime_cpp — in-tree fallback for
#      scaffolds living under <framework>/examples/<svc>/.
# See docs/runtime_cpp_install.md for full install/setup details.
find_package(MicroserviceBase CONFIG QUIET)
if(NOT MicroserviceBase_FOUND)
    set(_mb_candidates "")
    if(DEFINED ENV{{MICROSERVICEBASE_DIR}})
        list(APPEND _mb_candidates
            "$ENV{{MICROSERVICEBASE_DIR}}/MicroserviceBase/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}")
    endif()
    list(APPEND _mb_candidates
        "${{CMAKE_CURRENT_SOURCE_DIR}}/../../MicroserviceBase/runtime_cpp")
    set(_mb_in_tree "")
    foreach(_p IN LISTS _mb_candidates)
        if(EXISTS "${{_p}}/CMakeLists.txt")
            set(_mb_in_tree "${{_p}}")
            break()
        endif()
    endforeach()
    if(_mb_in_tree)
        message(STATUS "MicroserviceBase: using in-tree runtime at ${{_mb_in_tree}}")
        add_subdirectory("${{_mb_in_tree}}"
                         "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")
    else()
        message(FATAL_ERROR
            "MicroserviceBase runtime not found.  Either:\n"
            "  - set env var MICROSERVICEBASE_DIR to your framework checkout root\n"
            "    e.g.  setx MICROSERVICEBASE_DIR D:\\workspace\\python-microservice-base\n"
            "  - or install + set CMAKE_PREFIX_PATH / MicroserviceBase_ROOT\n"
            "    (see docs/runtime_cpp_install.md in the framework repo).")
    endif()
endif()
{_MB_DEPLOY_RUNTIME_BLOCK}
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
    header = cpp_file_header(
        "main.cpp",
        f"Entry point for the {svc} service.\n"
        f"Composes Settings, the domain class, and the gRPC adapter, then\n"
        f"hands them to ServiceRunner which manages the gRPC server\n"
        f"lifecycle and Consul registration.",
    )
    return f'''{header}
#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "domain/{grpc_name}.h"
#include "adapters/api/{svc}GrpcAdapter.h"

/**
 * Process entry point.
 *
 * Constructs the dependency-injection wiring (Settings -> domain ->
 * gRPC adapter), registers the adapter with ServiceRunner under the
 * fully-qualified service name "{pkg}.{grpc_name}", and serves until
 * a shutdown signal arrives (SIGINT / SIGTERM / Windows SIGBREAK).
 *
 * @return 0 on clean shutdown, 1 on fatal startup error.
 */
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
    header = cpp_file_header(
        "Settings.h",
        f"Service-specific settings for {spec.service_name}.\n"
        f"Loads all base fields (service_host, grpc_port, advertise_addr,\n"
        f"consul_addr, consul_token, log_level) from environment variables\n"
        f"prefixed with `{prefix}`.  Add service-specific fields below by\n"
        f"declaring members and calling readEnv() inside the constructor.",
    )
    return f'''{header}
#pragma once

#include "MicroserviceBase/Settings.h"

namespace {sn} {{

/**
 * Settings for the {spec.service_name} service.
 *
 * Inherits the standard fields from BaseServiceSettings.  Add
 * service-specific fields here as plain data members and read them
 * from the environment in the constructor using
 * `readEnv("{prefix}MY_FIELD", my_field_)`.
 */
struct Settings : public microservice_base::BaseServiceSettings {{
    /**
     * Construct settings, loading every base field from `{prefix}*`
     * environment variables.  Defaults from BaseServiceSettings apply
     * when an env var is unset.
     */
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

    header = cpp_file_header(
        f"{grpc_name}.h",
        f"Domain class for the {spec.service_name} service.\n"
        f"Pure business logic — no gRPC, no I/O, no protobuf types.\n"
        f"All inbound traffic enters through the gRPC adapter and is\n"
        f"translated into method calls on this class.",
    )

    if imported:
        return f'''{header}
#pragma once

#include <string>

namespace {sn} {{

/**
 * Domain class for {spec.service_name} (imported proto).
 *
 * The wizard couldn't infer the right method signatures from your
 * imported .proto file — add one method per RPC, matching the
 * request/response message types your adapter will pass in.
 */
class {grpc_name} {{
public:
    // TODO: add domain methods for your imported proto here.
}};

}}  // namespace {sn}
'''

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        # Doxygen block per method
        param_doc = "\n".join(
            f"     * @param {p.name} TODO: describe ``{p.name}``."
            for p in m.params
        )
        methods += (
            f"\n    /**\n"
            f"     * {m.name} — TODO: describe what this RPC does.\n"
            + (f"     *\n{param_doc}\n" if param_doc else "")
            + f"     *\n"
            f"     * @return TODO: describe the return value.  The default\n"
            f"     *         stub returns the literal string \"not implemented\".\n"
            f"     */\n"
            f"    std::string {_snake(m.name)}({params}) const;\n"
        )

    return f'''{header}
#pragma once

#include <string>

namespace {sn} {{

/**
 * Domain class for {spec.service_name}.
 *
 * One method per RPC declared in the .proto file.  Edit the bodies
 * in {grpc_name}.cpp to plug in real logic; the gRPC adapter calls
 * these methods on every inbound RPC.
 */
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

    header = cpp_file_header(
        f"{grpc_name}.cpp",
        f"Domain implementations for {spec.service_name}.\n"
        f"Replace each TODO body with the real business logic.  Method\n"
        f"signatures must stay aligned with {grpc_name}.h so the gRPC\n"
        f"adapter can keep calling them without changes.",
    )

    if imported:
        return f'''{header}
#include "{grpc_name}.h"

namespace {sn} {{

// TODO: add domain implementations for your imported proto here.

}}  // namespace {sn}
'''

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        methods += f'''
/**
 * {m.name} — TODO: implement.  See header for the per-parameter doc.
 *
 * The default stub returns the literal "not implemented" so the
 * service still builds and responds to RPCs end-to-end.
 */
std::string {grpc_name}::{_snake(m.name)}({params}) const {{
    // TODO: implement
    return "not implemented";
}}
'''

    return f'''{header}
#include "{grpc_name}.h"

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
                f"    /**\n"
                f"     * Handle a server-streaming {m.name} RPC.  Writes one or more\n"
                f"     * {outT} responses to the writer.\n"
                f"     *\n"
                f"     * @param ctx     gRPC server context (deadline, metadata, …).\n"
                f"     * @param request Inbound {inT}.\n"
                f"     * @param writer  Stream writer to push responses through.\n"
                f"     * @return        grpc::Status::OK on success.\n"
                f"     */\n"
                f"    grpc::Status {m.name}(grpc::ServerContext* ctx,\n"
                f"        const {inT}* request,\n"
                f"        grpc::ServerWriter<{outT}>* writer) override;\n\n"
            )
        else:
            methods += (
                f"    /**\n"
                f"     * Handle a unary {m.name} RPC.\n"
                f"     *\n"
                f"     * @param ctx      gRPC server context.\n"
                f"     * @param request  Inbound {inT}.\n"
                f"     * @param response {outT} populated by this method.\n"
                f"     * @return         grpc::Status::OK on success.\n"
                f"     */\n"
                f"    grpc::Status {m.name}(grpc::ServerContext* ctx,\n"
                f"        const {inT}* request,\n"
                f"        {outT}* response) override;\n\n"
            )

    grpc_name = _grpc_svc_name(spec)
    header = cpp_file_header(
        f"{svc}GrpcAdapter.h",
        f"gRPC inbound adapter for {grpc_name}.\n"
        f"Translates protobuf request/response messages into method calls\n"
        f"on the {grpc_name} domain class.  One method per RPC, generated\n"
        f"from the .proto file.  Do not change the signatures (they are\n"
        f"required by the proto-generated servicer base class); edit only\n"
        f"the bodies in {svc}GrpcAdapter.cpp to plug in real logic.",
    )
    return f'''{header}
#pragma once

#include <grpcpp/grpcpp.h>
#include "{sn}.grpc.pb.h"
#include "domain/{grpc_name}.h"

namespace {sn} {{

/**
 * gRPC servicer adapter for {grpc_name}.
 *
 * Holds a non-owning reference to the domain instance and forwards
 * each inbound RPC to it after unpacking the proto request fields.
 */
class {svc}GrpcAdapter final : public {ns}::{grpc_name}::Service {{
public:
    /**
     * Wire the adapter to the domain service.
     *
     * @param domain Reference to the domain instance.  Must outlive
     *               the adapter (typically both live for the duration
     *               of main()).
     */
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

    header = cpp_file_header(
        f"{svc}GrpcAdapter.cpp",
        f"Implementations for {svc}GrpcAdapter.\n"
        f"Each method unpacks the proto request, calls into the domain\n"
        f"object via m_domain, and packs the result into the response\n"
        f"message.  Imported-proto methods emit UNIMPLEMENTED until the\n"
        f"author wires them up — the service still builds and starts.",
    )
    return f'''{header}
#include "{svc}GrpcAdapter.h"

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
    "${{STUB_INC}}"
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
)
mb_deploy_runtime({sn}_gui QT_APP)'''

    return {
        "client/CMakeLists.txt": f'''cmake_minimum_required(VERSION 3.16)

# vcpkg auto-detection BEFORE project() - same pattern as the parent
# server CMakeLists, with paths climbing one level (../triplets, ../ports).
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "{svc}Client: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.  Set VCPKG_ROOT or pass "
        "-DCMAKE_TOOLCHAIN_FILE=... directly.")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (auto-set from ../triplets overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets"
            CACHE PATH "vcpkg overlay triplets directory")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports"
            CACHE PATH "vcpkg overlay ports directory")
    endif()
endif()
if(NOT DEFINED QT_CREATOR_SKIP_VCPKG_SETUP)
    set(QT_CREATOR_SKIP_VCPKG_SETUP ON CACHE BOOL "")
endif()
if(NOT CMAKE_MAKE_PROGRAM)
    set(_ninja_candidates "C:/Qt/Tools/Ninja/ninja.exe" "C:/Qt/Tools/Ninja_64/ninja.exe")
    if(DEFINED ENV{{VCPKG_ROOT}})
        file(GLOB _vcpkg_ninja "$ENV{{VCPKG_ROOT}}/downloads/tools/ninja-*/ninja.exe")
        list(APPEND _ninja_candidates ${{_vcpkg_ninja}})
    endif()
    foreach(_n IN LISTS _ninja_candidates)
        if(EXISTS "${{_n}}")
            set(CMAKE_MAKE_PROGRAM "${{_n}}" CACHE FILEPATH "Ninja (auto-detected)")
            break()
        endif()
    endforeach()
endif()

project({svc}Client VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# NOTE: skip the classic-mode x64-windows fallback - mixing MSVC libs into
# a MinGW link command yields `-ignore:4221` errors.  See parent CMakeLists.

# Manifest-mode fallback (mirror of parent CMakeLists): use prebuilt
# vcpkg_installed/x64-mingw-qt/ from build dir if vcpkg toolchain didn't load.
if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc (target triplet)")
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)

# MicroserviceBase runtime — provides ServiceClient<T>.  Resolution order:
#   1. find_package() — installed package or vcpkg overlay
#   2. MICROSERVICEBASE_DIR env var (set once, works from any location)
#   3. ../../../MicroserviceBase/runtime_cpp — in-tree fallback for
#      <framework>/examples/<svc>/client/.
find_package(MicroserviceBase CONFIG QUIET)
if(NOT MicroserviceBase_FOUND)
    set(_mb_candidates "")
    if(DEFINED ENV{{MICROSERVICEBASE_DIR}})
        list(APPEND _mb_candidates
            "$ENV{{MICROSERVICEBASE_DIR}}/MicroserviceBase/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}")
    endif()
    list(APPEND _mb_candidates
        "${{CMAKE_CURRENT_SOURCE_DIR}}/../../../MicroserviceBase/runtime_cpp")
    set(_mb_in_tree "")
    foreach(_p IN LISTS _mb_candidates)
        if(EXISTS "${{_p}}/CMakeLists.txt")
            set(_mb_in_tree "${{_p}}")
            break()
        endif()
    endforeach()
    if(_mb_in_tree)
        add_subdirectory("${{_mb_in_tree}}"
                         "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")
    else()
        message(FATAL_ERROR
            "MicroserviceBase runtime not found.  Set MICROSERVICEBASE_DIR env var "
            "to your framework checkout, or install + add to CMAKE_PREFIX_PATH "
            "(see docs/runtime_cpp_install.md in the framework repo).")
    endif()
endif()

# Proto stubs - shared with the service via ../proto/.
# Two modes:
#   1. Pre-generated: stubs exist in ../proto/ (run generate_stubs.bat once).
#   2. Auto-generate: run protoc/grpc_cpp_plugin at build time into build/gen/.
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/../proto")

if(EXISTS "${{PROTO_DIR}}/{sn}.pb.h")
    set(STUB_SRCS
        "${{PROTO_DIR}}/{sn}.pb.cc"
        "${{PROTO_DIR}}/{sn}.grpc.pb.cc")
    set(STUB_INC "${{PROTO_DIR}}")
else()
    set(GEN_DIR "${{CMAKE_CURRENT_BINARY_DIR}}/gen")
    file(MAKE_DIRECTORY "${{GEN_DIR}}")
    set(STUB_SRCS
        "${{GEN_DIR}}/{sn}.pb.cc"
        "${{GEN_DIR}}/{sn}.grpc.pb.cc")
    set(STUB_INC "${{GEN_DIR}}")
    if(TARGET protobuf::protoc)
        get_target_property(_protoc protobuf::protoc LOCATION)
    else()
        find_program(_protoc NAMES protoc protoc.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/protobuf"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf"
            REQUIRED)
    endif()
    if(TARGET gRPC::grpc_cpp_plugin)
        get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin LOCATION)
    else()
        find_program(_grpc_cpp NAMES grpc_cpp_plugin grpc_cpp_plugin.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/grpc"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/grpc"
            REQUIRED)
    endif()
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
        COMMENT "Auto-generating gRPC stubs into ${{GEN_DIR}}")
endif()

{_MB_DEPLOY_RUNTIME_BLOCK}
add_executable({sn}_client
    src/client.cpp
    ${{STUB_SRCS}}
)

target_include_directories({sn}_client PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{STUB_INC}}"
)

target_link_libraries({sn}_client PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
)
mb_deploy_runtime({sn}_client){gui_block}
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

    # ------ Optional Qt-native client (qt_client/) ------
    if spec.gui_type != "none" and spec.client_grpc_kind == "qt":
        files.update(_qt_client_files(spec, services=services))

    # ------ Optional qt_client_grpcpp (Google grpc++ via vcpkg + Qt MinGW) ------
    client_uses_vcpkg = (spec.gui_type != "none"
                        and spec.client_grpc_kind == "google_vcpkg")
    if client_uses_vcpkg:
        files.update(_qt_client_grpcpp_files(spec, services=services))

    # ------ Server vcpkg path (Google grpc++ via vcpkg + Qt MinGW) ------
    server_uses_vcpkg = spec.server_grpc_kind == "vcpkg"
    if server_uses_vcpkg:
        files["vcpkg.json"] = _server_vcpkg_json(spec)
        if spec.gen_build_scripts:
            files["build_qt_vcpkg.bat"] = _server_build_qt_vcpkg_bat(spec)
            files["deploy_qt_vcpkg.bat"] = _server_deploy_qt_vcpkg_bat(spec)
            if spec.gui_type != "none" and spec.client_grpc_kind == "google":
                files["client/deploy_qt_vcpkg.bat"] = _client_deploy_qt_vcpkg_bat(spec)

    # ------ Shared vcpkg infrastructure (triplets/ + ports/ + scripts) ------
    if client_uses_vcpkg or server_uses_vcpkg:
        files.update(_vcpkg_shared_files(spec))

    # ------ README (Markdown + HTML guide) ------
    if spec.gen_readme:
        files["README.md"]   = _mono_readme(spec, services)
        files["README.html"] = _mono_readme_html(spec, services)

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
    gRPC::grpc++ ${{GRPC_REFL_LIB}}
    protobuf::libprotobuf
)
mb_deploy_runtime({svc_snake})
'''.rstrip())

    exe_joined = '\n'.join(exe_blocks)

    return f'''cmake_minimum_required(VERSION 3.16)

# vcpkg auto-detection BEFORE project() so the toolchain loads correctly.
# See server CMakeLists in cpp_tmpl.py's _cmake() for the full rationale.
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "{project_name}: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.  Set VCPKG_ROOT or pass "
        "-DCMAKE_TOOLCHAIN_FILE=... directly.")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (auto-set from triplets/ overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/triplets"
            CACHE PATH "vcpkg overlay triplets directory")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/ports"
            CACHE PATH "vcpkg overlay ports directory")
    endif()
endif()
if(NOT DEFINED QT_CREATOR_SKIP_VCPKG_SETUP)
    set(QT_CREATOR_SKIP_VCPKG_SETUP ON CACHE BOOL "")
endif()
if(NOT CMAKE_MAKE_PROGRAM)
    set(_ninja_candidates "C:/Qt/Tools/Ninja/ninja.exe" "C:/Qt/Tools/Ninja_64/ninja.exe")
    if(DEFINED ENV{{VCPKG_ROOT}})
        file(GLOB _vcpkg_ninja "$ENV{{VCPKG_ROOT}}/downloads/tools/ninja-*/ninja.exe")
        list(APPEND _ninja_candidates ${{_vcpkg_ninja}})
    endif()
    foreach(_n IN LISTS _ninja_candidates)
        if(EXISTS "${{_n}}")
            set(CMAKE_MAKE_PROGRAM "${{_n}}" CACHE FILEPATH "Ninja (auto-detected)")
            break()
        endif()
    endforeach()
endif()

project({project_name} VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Manifest-mode fallback: when vcpkg toolchain didn't load but a populated
# vcpkg_installed/x64-mingw-qt/ exists in the build dir.
if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc (target triplet)")
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# gRPC server reflection - present in both supported toolchains (MSYS2's
# stock grpc; our vcpkg overlay-port which forces gRPC_BUILD_CODEGEN=ON).
# Kept as a guard for unusual grpc distributions that omit it.
if(TARGET gRPC::grpc++_reflection)
    set(GRPC_REFL_LIB gRPC::grpc++_reflection)
else()
    set(GRPC_REFL_LIB "")
endif()

# Shared MicroserviceBase runtime — resolution order:
#   1. find_package() — installed package or vcpkg overlay-port
#   2. MICROSERVICEBASE_DIR env var pointing at framework checkout
#   3. ../../MicroserviceBase/runtime_cpp — in-tree fallback for monorepos
#      living at <framework>/examples/<monorepo>/.
find_package(MicroserviceBase CONFIG QUIET)
if(NOT MicroserviceBase_FOUND)
    set(_mb_candidates "")
    if(DEFINED ENV{{MICROSERVICEBASE_DIR}})
        list(APPEND _mb_candidates
            "$ENV{{MICROSERVICEBASE_DIR}}/MicroserviceBase/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}")
    endif()
    list(APPEND _mb_candidates
        "${{CMAKE_CURRENT_SOURCE_DIR}}/../../MicroserviceBase/runtime_cpp")
    set(_mb_in_tree "")
    foreach(_p IN LISTS _mb_candidates)
        if(EXISTS "${{_p}}/CMakeLists.txt")
            set(_mb_in_tree "${{_p}}")
            break()
        endif()
    endforeach()
    if(_mb_in_tree)
        add_subdirectory("${{_mb_in_tree}}"
                         "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")
    else()
        message(FATAL_ERROR
            "MicroserviceBase runtime not found.  Set MICROSERVICEBASE_DIR env "
            "var to your framework checkout, or install + add to CMAKE_PREFIX_PATH "
            "(see docs/runtime_cpp_install.md).")
    endif()
endif()

{_MB_DEPLOY_RUNTIME_BLOCK}
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
    # Tolerant lookup: vcpkg's grpc port built without the `codegen`
    # feature does NOT define gRPC::grpc_cpp_plugin.  Fall back to
    # find_program against the host-tools dir (x64-windows/tools).
    if(TARGET protobuf::protoc)
        get_target_property(_protoc protobuf::protoc LOCATION)
    else()
        find_program(_protoc NAMES protoc protoc.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/protobuf"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf"
            REQUIRED)
    endif()
    if(TARGET gRPC::grpc_cpp_plugin)
        get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin LOCATION)
    else()
        find_program(_grpc_cpp NAMES grpc_cpp_plugin grpc_cpp_plugin.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/grpc"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/grpc"
            REQUIRED)
    endif()
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


def _readme_env_section_html(uses_vcpkg: bool, uses_qt6_grpc: bool) -> str:
    """Concrete env-var setup steps for the README.  Bullets the user can
    copy/paste verbatim.  Conditional on whether vcpkg / Qt6::Grpc is in use."""
    if not uses_vcpkg:
        # MSYS2-only path.  Just MSYS2 + Qt env vars.
        return '''
        <p>For the MSYS2-only path, set:</p>
        <pre><code>setx MSYS2_ROOT C:\\msys64\\mingw64</code></pre>
        <p>Open a new terminal afterwards so the env var is inherited.</p>
        <p>If you also build the Qt-installer client variant
           (<code>qt_client/</code>), see
           <code>examples/docs/html/qt_grpc_setup.html</code> for the
           additional <code>QT_DIR</code> / <code>PROTOC_DIR</code> setup.</p>'''
    parts = ['''
        <p>The vcpkg path needs three environment variables.  Set them once
           system-wide via <code>setx</code> &mdash; <strong>then close every
           open terminal/Qt Creator and start a fresh one</strong> so the new
           values are inherited (<code>setx</code> only affects new processes).</p>
        <h3>1. <code>VCPKG_ROOT</code> &mdash; vcpkg checkout</h3>
        <p>If you don&rsquo;t have vcpkg installed yet:</p>
        <pre><code>git clone https://github.com/microsoft/vcpkg.git C:\\vcpkg
C:\\vcpkg\\bootstrap-vcpkg.bat</code></pre>
        <p>Then point <code>VCPKG_ROOT</code> at it:</p>
        <pre><code>setx VCPKG_ROOT C:\\vcpkg</code></pre>
        <p>(Replace <code>C:\\vcpkg</code> with wherever you cloned it,
           e.g. <code>D:\\Project\\Out\\vcpkg</code>.)</p>

        <h3>2. <code>QT_DIR</code> &mdash; Qt MinGW prefix</h3>
        <p>Path to the directory containing <code>lib\\cmake\\Qt6\\</code>:</p>
        <pre><code>setx QT_DIR C:\\Qt\\6.11.0\\mingw_64</code></pre>
        <p>(Adjust the version number to your actual Qt install.)</p>

        <h3>3. <code>QT_MINGW_BIN</code> &mdash; Qt MinGW compiler bin</h3>
        <p>Path to the directory containing <code>g++.exe</code>:</p>
        <pre><code>setx QT_MINGW_BIN C:\\Qt\\Tools\\mingw1310_64\\bin</code></pre>

        <h3>Verify</h3>
        <p>Open a new terminal and run:</p>
        <pre><code>echo %VCPKG_ROOT%
echo %QT_DIR%
echo %QT_MINGW_BIN%
dir %VCPKG_ROOT%\\vcpkg.exe
dir %QT_DIR%\\bin\\Qt6Core.dll
dir %QT_MINGW_BIN%\\g++.exe</code></pre>
        <p>All three <code>dir</code> commands should print a file entry.
           If any errors with <em>File Not Found</em>, double-check the path
           and re-run <code>setx</code>.</p>

        <h3>For Qt Creator specifically</h3>
        <p>If Qt Creator was already running when you set these vars, it
           won&rsquo;t see the new values until restarted.  Either:</p>
        <ul>
          <li><strong>Close + restart Qt Creator</strong> (simplest), or</li>
          <li>Set them per-project at <em>Projects &rarr; Build &rarr;
              Build Environment</em> (Add &rarr; type the var + value).</li>
        </ul>''']
    if uses_qt6_grpc:
        parts.append('''
        <h3>Qt 6.7 only: enable Qt GRPC + Qt Protobuf modules</h3>
        <p>Qt 6.5&ndash;6.7 ship Qt GRPC as a Tech Preview that&rsquo;s NOT
           installed by default.  Open the Qt Maintenance Tool, find your
           6.7.x &rarr; <strong>MinGW 64-bit</strong> entry, and tick
           <em>Qt GRPC</em> + <em>Qt Protobuf</em> + <em>Qt Protobuf
           WellKnownTypes</em>.  Qt 6.8+ has them stable + on by default.</p>''')
    return "".join(parts)


def _mono_readme_html(spec, services) -> str:
    """HTML walkthrough emitted alongside README.md.  Conditional on
    spec.client_grpc_kind / spec.server_grpc_kind so it only documents
    the tools that exist in this scaffold."""
    proj = spec.service_name
    sn = spec.snake_name
    svc_uses_vcpkg = spec.server_grpc_kind == "vcpkg"
    cli_uses_vcpkg = (spec.gui_type != "none"
                     and spec.client_grpc_kind == "google_vcpkg")
    has_console_client = True
    has_widget_gui = (spec.gui_type == "widget"
                     and spec.client_grpc_kind in ("google", "google_vcpkg"))
    has_qt6_grpc_client = (spec.gui_type != "none"
                          and spec.client_grpc_kind == "qt")

    svc_rows = "\n".join(
        f'        <tr><td><code>{s.name}</code></td>'
        f'<td>{len(s.methods)}</td><td><code>{_mono_snake(s.name).upper()}_</code></td></tr>'
        for s in services
    )

    # Conditional sections built up.
    sections = []

    # ---- Quick reference table ----
    cmds = []
    if svc_uses_vcpkg:
        cmds.append(('Build server (vcpkg + Qt MinGW)', 'build_qt_vcpkg.bat'))
        cmds.append(('Deploy server', 'deploy_qt_vcpkg.bat'))
    cmds.append(('Build server (MSYS2)', 'build_deploy_msys2.bat'))
    if has_widget_gui:
        if svc_uses_vcpkg:
            cmds.append(('Build/deploy console + widget client (vcpkg)', 'cd client &amp;&amp; deploy_qt_vcpkg.bat'))
    if cli_uses_vcpkg:
        cmds.append(('Build qt_client_grpcpp', 'cd qt_client_grpcpp &amp;&amp; build_qt.bat'))
        cmds.append(('Deploy qt_client_grpcpp', 'cd qt_client_grpcpp &amp;&amp; deploy_qt.bat'))
    if has_qt6_grpc_client:
        cmds.append(('Build qt_client (Qt6::Grpc)', 'cd qt_client &amp;&amp; build_qt.bat'))
    if svc_uses_vcpkg or cli_uses_vcpkg:
        cmds.append(('Import a teammate&rsquo;s prebuilt vcpkg artifacts', 'import_prebuilt.bat &lt;path&gt;.zip'))
        cmds.append(('Export prebuilt for sharing', 'export_prebuilt.bat'))
    cmds.append(('Resolve Nomad HCL placeholders', 'prep_nomad_paths.bat'))
    quick_rows = "\n".join(
        f'        <tr><td>{desc}</td><td><code>{cmd}</code></td></tr>'
        for desc, cmd in cmds
    )

    # ---- Prerequisites ----
    prereqs = []
    prereqs.append('Windows 10 1803+ (for built-in <code>tar.exe</code>)')
    if svc_uses_vcpkg or cli_uses_vcpkg:
        prereqs.append('Qt 6.x with MinGW 13.1.0 kit (online installer)')
        prereqs.append('vcpkg cloned + bootstrapped, <code>VCPKG_ROOT</code> env var set')
        prereqs.append('Env vars: <code>QT_DIR=C:\\Qt\\6.x.y\\mingw_64</code>, '
                      '<code>QT_MINGW_BIN=C:\\Qt\\Tools\\mingw1310_64\\bin</code>')
    if has_qt6_grpc_client:
        prereqs.append('Qt 6.8+ with <strong>Qt GRPC</strong> + <strong>Qt Protobuf</strong> modules ticked in Maintenance Tool')
    prereqs.append('Consul + Nomad agents (if you plan to run via Nomad)')
    prereq_html = "\n".join(f'        <li>{p}</li>' for p in prereqs)

    # ---- How vcpkg + Qt MinGW works (rationale) ----
    rationale_html = ""
    if svc_uses_vcpkg or cli_uses_vcpkg:
        rationale_html = '''
        <p>
          Both server and client need Google&rsquo;s grpc++ and protobuf C++
          libraries.  We compile them <strong>from source via vcpkg</strong>
          using the <strong>Qt-installer&rsquo;s MinGW 13.1.0</strong>
          compiler so every binary in the project shares one libstdc++ ABI.
          Mixing toolchains (e.g. MSYS2 grpc + Qt MinGW client) yields
          cryptic link errors and silent crashes at <code>std::string</code>
          boundaries.
        </p>
        <p>The pieces that make this work:</p>
        <ol>
          <li><strong><code>triplets/x64-mingw-qt.cmake</code></strong> &mdash;
              custom vcpkg triplet.  Pins <code>VCPKG_TARGET_ARCHITECTURE=x64</code>,
              dynamic CRT/library linkage, and chainloads
              <code>qt-mingw-toolchain.cmake</code> which sets
              <code>CMAKE_C_COMPILER</code> and <code>CMAKE_CXX_COMPILER</code>
              to absolute paths inside <code>C:\\Qt\\Tools\\mingw1310_64\\bin\\</code>.
              Vcpkg uses Qt&rsquo;s gcc to build every port regardless of
              what&rsquo;s on <code>PATH</code>.</li>
          <li><strong><code>ports/grpc/00018-gcc13-per-cpu-ice-workaround.patch</code></strong>
              &mdash; gcc 13.1.0 has an internal compiler error on grpc 1.76&rsquo;s
              <code>per_cpu.h</code> NSDMI brace-init.  The patch moves the
              <code>std::unique_ptr&lt;T[]&gt;</code> allocation into the
              constructor body, sidestepping the ICE.  An overlay-port
              applies it on top of vcpkg&rsquo;s stock grpc port.</li>
          <li><strong>Host tools (cross-triplet codegen)</strong> &mdash;
              vcpkg builds <code>protoc</code> and <code>grpc_cpp_plugin</code>
              for the host triplet (<code>x64-windows</code>) and uses them at
              build time to generate <code>.pb.h/.pb.cc</code> stubs.  Our
              CMakeLists pre-sets <code>Protobuf_PROTOC_EXECUTABLE</code> at
              <code>build/.../vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe</code>
              so it doesn&rsquo;t require <code>x64-windows/tools/protobuf/</code>.
              <code>grpc_cpp_plugin</code> still ships from
              <code>x64-windows/tools/grpc/</code> because vcpkg&rsquo;s grpc
              port doesn&rsquo;t build it for the target triplet.</li>
          <li><strong>Server reflection</strong> &mdash; the overlay-port
              forces <code>gRPC_BUILD_CODEGEN=ON</code> in
              <code>portfile.cmake</code>, which causes upstream grpc to
              build and install <code>libgrpc++_reflection.a</code> +
              register the <code>gRPC::grpc++_reflection</code> CMake
              target.  Without that override, vcpkg&rsquo;s manifest-mode
              feature selection drops <code>codegen</code> for the target
              triplet (it stays on for the host triplet only) and
              upstream&rsquo;s <code>add_library(grpc++_reflection ...)</code>
              block gets skipped &mdash; the Manager GUI then sees
              <code>UNIMPLEMENTED</code> from every reflection RPC.
              CMakeLists keeps an <code>if(TARGET gRPC::grpc++_reflection)</code>
              guard for unusual grpc distributions; the bridge also
              has a <code>LocalProtoClient</code> fallback that compiles
              <code>.proto</code> files from disk if reflection is
              somehow still missing.</li>
          <li><strong>vcpkg.json declares</strong> grpc + protobuf + curl
              (Consul HTTP), with <code>features: ["codegen"]</code> for grpc
              so <code>protoc-gen-grpc</code> is available.  Manifest names
              are hyphenated (<code>{spec.snake_name.replace('_', '-')}-server-vcpkg</code>);
              underscores are reserved.</li>
        </ol>
        <p>
          <strong>First build cost</strong>: vcpkg compiles boringssl, abseil,
          c-ares, re2, zlib, openssl, protobuf, grpc, curl &mdash; about
          30&ndash;60 min on a typical workstation, mostly idle.  Subsequent
          builds in the same triplet hit the binary cache at
          <code>%LOCALAPPDATA%\\vcpkg\\archives\\</code> and complete in seconds.
        </p>'''.replace('{spec.snake_name', '{' + spec.snake_name)  # placeholder kept

    # ---- CLI build (step by step) ----
    cli_steps = []
    if svc_uses_vcpkg:
        cli_steps.append((
            'One-time: set environment variables',
            f'<pre><code>setx VCPKG_ROOT C:\\vcpkg\nsetx QT_DIR C:\\Qt\\6.11.0\\mingw_64\nsetx QT_MINGW_BIN C:\\Qt\\Tools\\mingw1310_64\\bin</code></pre>'
            '<p>Then open a fresh terminal so the env vars are inherited.</p>'))
        cli_steps.append((
            'Initialise the vcpkg overlay-port (idempotent)',
            '<pre><code>init_vcpkg_overlay.bat</code></pre>'
            '<p>Copies vcpkg&rsquo;s upstream grpc port into <code>ports/grpc/</code> '
            'and appends our gcc 13 ICE workaround patch.  No-op on subsequent runs.</p>'))
        cli_steps.append((
            f'Build the server (and runs vcpkg install on first invocation)',
            '<pre><code>build_qt_vcpkg.bat</code></pre>'
            '<p>First time: ~30&ndash;60 min while vcpkg compiles boringssl + abseil + '
            'protobuf + grpc + curl.  Subsequent runs: cache hit, ~1&ndash;3 min.  '
            'Output: <code>build-qt-vcpkg\\&lt;service&gt;.exe</code>.</p>'))
        cli_steps.append((
            'Bundle a self-contained dist',
            '<pre><code>deploy_qt_vcpkg.bat</code></pre>'
            f'<p>Copies <code>.exe</code> + vcpkg DLLs + MinGW runtime + Qt DLLs '
            f'into <code>dist-qt-vcpkg\\</code>.  Zip + copy to any Win x64 PC; '
            f'no Qt/vcpkg/MinGW install needed on target.</p>'))
    else:
        cli_steps.append((
            'Build server via MSYS2',
            '<pre><code>build_deploy_msys2.bat</code></pre>'
            '<p>Uses MSYS2&rsquo;s prebuilt mingw-w64-x86_64-grpc.  See '
            '<code>examples/docs/html/mingw_setup.html</code> for MSYS2 setup.</p>'))
    if has_widget_gui and svc_uses_vcpkg:
        cli_steps.append((
            'Build console + Qt Widgets client',
            '<pre><code>cd client\nbuild script: open client\\CMakeLists.txt in Qt Creator,\n'
            'or use a one-liner:\ncmake -S . -B build-qt-vcpkg -G Ninja \\\n'
            '    -DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake \\\n'
            '    -DVCPKG_TARGET_TRIPLET=x64-mingw-qt \\\n'
            '    -DVCPKG_OVERLAY_TRIPLETS=../triplets \\\n'
            '    -DVCPKG_OVERLAY_PORTS=../ports\ncmake --build build-qt-vcpkg --parallel\n'
            'deploy_qt_vcpkg.bat</code></pre>'))
    if cli_uses_vcpkg:
        cli_steps.append((
            'Build the Qt grpc++ client',
            '<pre><code>cd qt_client_grpcpp\nbuild_qt.bat\ndeploy_qt.bat</code></pre>'))
    if has_qt6_grpc_client:
        cli_steps.append((
            'Build the Qt6::Grpc client',
            '<pre><code>cd qt_client\nbuild_qt.bat</code></pre>'))
    cli_html = "\n".join(
        f'        <li><strong>{title}</strong><br>{body}</li>'
        for title, body in cli_steps
    )

    # ---- Full step-by-step kit-flow walkthrough ----
    # The "do this and you'll succeed" recipe for users who want to load
    # both the server and qt_client_grpcpp/ in Qt Creator with the
    # Desktop Qt 6.x MinGW 64-bit kit (NOT the preset) and skip the 30-60
    # min vcpkg compile.  Only emitted when the project actually has the
    # vcpkg toolchain pieces.
    full_kit_walkthrough_html = ""
    if svc_uses_vcpkg and cli_uses_vcpkg:
        full_kit_walkthrough_html = '''
  <section id="full-kit-walkthrough">
    <h2>Full step-by-step: load both projects in Qt Creator with the
        <code>Desktop Qt 6.x MinGW 64-bit</code> kit, no rebuild</h2>

    <p>
      The fastest path that loads <strong>both</strong> the server (this
      project) and the <code>qt_client_grpcpp/</code> client into Qt
      Creator with the <code>Desktop Qt 6.x MinGW 64-bit</code> kit
      (no preset, no full vcpkg compile).  Follow exactly &mdash; each
      step prevents a common pitfall covered in the troubleshooting
      section.
    </p>

    <h3>One-time setup</h3>
    <ol>
      <li><strong>Set system env vars</strong> (in a regular CMD, replace
          the paths with yours if different):
        <pre><code>setx VCPKG_ROOT C:\\vcpkg
setx QT_DIR C:\\Qt\\6.11.0\\mingw_64
setx QT_MINGW_BIN C:\\Qt\\Tools\\mingw1310_64\\bin</code></pre>
        <code>setx</code> writes the registry &mdash; only future
        processes see the change.</li>
      <li><strong>Fully close Qt Creator</strong>.  Check Task Manager for
          stray <code>qtcreator.exe</code> and kill them.  Otherwise the
          running Qt Creator keeps the old (empty) env, and the autodetect
          block in CMakeLists won&rsquo;t see <code>VCPKG_ROOT</code>.</li>
      <li><strong>Download the prebuilt zip</strong> from the SharePoint
          link below (in the <em>Use prebuilt libraries</em> section) and
          save anywhere, e.g.
          <code>C:\\prebuilt\\vcpkg_installed_x64-mingw-qt.zip</code>.</li>
    </ol>

    <h3>Step 1 &mdash; configure the server (this) project</h3>
    <ol>
      <li>Open Qt Creator.  <em>File &rarr; Open File or Project</em>
          &rarr; pick this project&rsquo;s <code>CMakeLists.txt</code>.</li>
      <li>Configure dialog: <strong>untick every preset</strong>.  Tick
          only the kit <strong>Desktop Qt 6.x MinGW 64-bit</strong>.
          Click <em>Configure Project</em>.</li>
      <li>The first configure may try to install vcpkg packages or fail
          at <code>find_package(gRPC)</code> &mdash; <strong>that&rsquo;s
          fine</strong>; we just need the build dir to exist.  If a long
          vcpkg compile starts: <em>Build &rarr; Cancel Build</em> immediately.</li>
      <li><em>Build &rarr; Clear CMake Configuration</em>.  This wipes
          <code>CMakeCache.txt</code> so the vars you&rsquo;re about to add
          actually take effect.  (<em>Clean</em> alone does NOT clear
          cache.)</li>
      <li><em>Projects (Ctrl+5) &rarr; Build (under
          Desktop Qt 6.x MinGW 64-bit) &rarr; Initial Configuration
          &rarr; Add</em>.  Add these <strong>five</strong> entries
          (replace placeholders with your vcpkg checkout and project
          absolute paths; leave forward slashes and the var-name S as
          written):
        <table>
          <tr><th>Add as</th><th>Name</th><th>Value</th></tr>
          <tr><td>String</td>  <td><code>CMAKE_TOOLCHAIN_FILE</code></td>   <td><code>C:/vcpkg/scripts/buildsystems/vcpkg.cmake</code></td></tr>
          <tr><td>String</td>  <td><code>VCPKG_TARGET_TRIPLET</code></td>   <td><code>x64-mingw-qt</code></td></tr>
          <tr><td>String</td>  <td><code>VCPKG_OVERLAY_TRIPLETS</code></td> <td><code>C:/path/to/your/project/triplets</code></td></tr>
          <tr><td>String</td>  <td><code>VCPKG_OVERLAY_PORTS</code></td>    <td><code>C:/path/to/your/project/ports</code></td></tr>
          <tr><td>Boolean</td> <td><code>VCPKG_MANIFEST_INSTALL</code></td> <td><code>OFF</code></td></tr>
        </table>
        Pitfall reminders:
        <ul>
          <li>Var name is <strong>plural</strong>:
              <code>VCPKG_OVERLAY_TRIPLETS</code> (with S).</li>
          <li>Use <strong>absolute paths</strong> for overlay vars.  Qt
              Creator does <strong>not</strong> expand
              <code>${sourceDir}</code> in <em>Initial Configuration</em>.</li>
          <li>Forward slashes <code>/</code> only.</li>
          <li><code>VCPKG_MANIFEST_INSTALL=OFF</code> is what tells the
              vcpkg toolchain to skip its 30&ndash;60 min compile.  Without
              this, vcpkg overwrites the prebuilt tree you&rsquo;re about
              to import.</li>
        </ul>
      </li>
      <li><em>Build &rarr; Run CMake</em>.  This will fail at
          <code>find_package(gRPC)</code> &mdash; <strong>expected</strong>:
          the build dir
          <code>build\\Desktop_Qt_*\\</code> is now created but
          <code>vcpkg_installed/</code> isn&rsquo;t populated yet.</li>
    </ol>

    <h3>Step 2 &mdash; configure the qt_client_grpcpp project</h3>
    <ol>
      <li><em>File &rarr; Open File or Project</em> &rarr;
          <code>qt_client_grpcpp\\CMakeLists.txt</code> (it&rsquo;s a
          separate sub-project with its own build dir).</li>
      <li>Configure dialog: <strong>untick every preset</strong>.  Tick
          only <strong>Desktop Qt 6.x MinGW 64-bit</strong>.  Click
          <em>Configure Project</em>.  Same as step 1: cancel any vcpkg
          compile, then <em>Clear CMake Configuration</em>.</li>
      <li><em>Projects (Ctrl+5) &rarr; Build &rarr; Initial Configuration
          &rarr; Add</em>.  Same five entries as the server, but the two
          overlay paths point at the <strong>parent</strong>
          <code>triplets/</code> and <code>ports/</code> (one level up
          from <code>qt_client_grpcpp/</code>):
        <table>
          <tr><th>Add as</th><th>Name</th><th>Value</th></tr>
          <tr><td>String</td>  <td><code>CMAKE_TOOLCHAIN_FILE</code></td>   <td><code>C:/vcpkg/scripts/buildsystems/vcpkg.cmake</code></td></tr>
          <tr><td>String</td>  <td><code>VCPKG_TARGET_TRIPLET</code></td>   <td><code>x64-mingw-qt</code></td></tr>
          <tr><td>String</td>  <td><code>VCPKG_OVERLAY_TRIPLETS</code></td> <td><code>C:/path/to/your/project/triplets</code></td></tr>
          <tr><td>String</td>  <td><code>VCPKG_OVERLAY_PORTS</code></td>    <td><code>C:/path/to/your/project/ports</code></td></tr>
          <tr><td>Boolean</td> <td><code>VCPKG_MANIFEST_INSTALL</code></td> <td><code>OFF</code></td></tr>
        </table>
      </li>
      <li><em>Build &rarr; Run CMake</em>.  Will fail at
          <code>find_package(Protobuf)</code> &mdash; expected; the
          <code>qt_client_grpcpp\\build\\Desktop_Qt_*\\</code> dir is now
          created.</li>
    </ol>

    <h3>Step 3 &mdash; populate vcpkg_installed/ from the prebuilt zip</h3>
    <ol>
      <li>Open a regular CMD/PowerShell.  <code>cd</code> to the
          <strong>parent project</strong> (this directory).</li>
      <li>Run import once &mdash; it auto-detects every build dir
          (server <strong>and</strong> qt_client_grpcpp) and extracts the
          zip into all of them:
        <pre><code>import_prebuilt.bat C:\\prebuilt\\vcpkg_installed_x64-mingw-qt.zip</code></pre>
      </li>
      <li>Verify both build dirs got the tree:
        <pre><code>dir build\\Desktop_Qt_*\\vcpkg_installed\\x64-mingw-qt\\share\\grpc\\
dir qt_client_grpcpp\\build\\Desktop_Qt_*\\vcpkg_installed\\x64-mingw-qt\\share\\grpc\\</code></pre>
        Both should list <code>gRPCConfig.cmake</code>.  If only one is
        present, your other project&rsquo;s build dir wasn&rsquo;t created
        yet &mdash; go back to whichever step you skipped.</li>
    </ol>

    <h3>Step 4 &mdash; re-run CMake on both projects</h3>
    <ol>
      <li>In Qt Creator, switch to the <strong>server</strong> project
          (top-left project selector) &rarr; <em>Build &rarr; Run CMake</em>.
          Should complete in ~1&ndash;3 sec.  In <em>General Messages</em>:
          <pre><code>-- Found gRPC: &lt;build-dir&gt;/vcpkg_installed/x64-mingw-qt/share/grpc
-- Found Protobuf: ...
-- Configuring done</code></pre>
      </li>
      <li>Switch to the <strong>qt_client_grpcpp</strong> project &rarr;
          <em>Build &rarr; Run CMake</em>.  Same ~1&ndash;3 sec result.</li>
      <li><em>Build &rarr; Build All</em> on both projects.  Project code
          compiles in ~30 sec &ndash; 2 min; vcpkg deps are
          <strong>not</strong> rebuilt.</li>
    </ol>

    <h3>Sanity check: did it really skip the rebuild?</h3>
    <p>In <em>General Messages</em> you should <strong>not</strong> see:</p>
    <pre><code>-- Building boringssl[core]:x64-mingw-qt...
-- Building abseil[core]:x64-mingw-qt...
-- Building grpc:x64-mingw-qt...</code></pre>
    <p>If you do, <code>VCPKG_MANIFEST_INSTALL=OFF</code> didn&rsquo;t reach
       the toolchain.  Check that:</p>
    <ul>
      <li>The Initial Configuration entry is type <strong>Boolean</strong>
          (or String <code>OFF</code>) &mdash; not deleted.</li>
      <li>You ran <em>Clear CMake Configuration</em> after adding it
          (cached configures don&rsquo;t pick up new <code>-D</code> flags).</li>
    </ul>
    <p>If you forgot one of the four toolchain vars or used a wrong path,
       the failure surfaces as <code>Could not find a package configuration
       file provided by &quot;gRPC&quot;</code> at <code>find_package</code>
       &mdash; not as a build of grpc itself.</p>
  </section>'''

    # ---- Qt Creator setup ----
    if svc_uses_vcpkg or cli_uses_vcpkg:
        qtc_html = '''
    <h3>Recommended: use the bundled CMake preset</h3>
    <ol>
        <li>Open <code>CMakeLists.txt</code> in Qt Creator.  Qt Creator detects the
            bundled <code>CMakePresets.json</code> and offers two presets:
          <ul>
            <li><strong>vcpkg-x64-mingw-qt</strong> &mdash; full vcpkg build (~30&ndash;60&nbsp;min first time).</li>
            <li><strong>vcpkg-x64-mingw-qt-prebuilt</strong> &mdash; skip vcpkg install
                (populate <code>build/.../vcpkg_installed/x64-mingw-qt/</code> first via
                <code>import_prebuilt.bat</code>).</li>
          </ul>
        </li>
        <li>Tick the preset(s) you want and click <em>Configure Project</em>.  Presets
            already include <code>CMAKE_TOOLCHAIN_FILE</code>,
            <code>VCPKG_TARGET_TRIPLET</code>, and overlay paths &mdash; no manual
            wiring required.</li>
    </ol>

    <h3>Alternative: kit-based flow (Desktop Qt 6.x MinGW 64-bit)</h3>
    <p>
      If you prefer to use a Qt kit instead of the preset, you must give Qt Creator
      the vcpkg toolchain explicitly &mdash; it does <strong>not</strong> auto-detect
      vcpkg from <code>VCPKG_ROOT</code> the way the CLI build script does.
    </p>
    <ol>
        <li><strong>Set system env vars (one-time)</strong>:
          <pre><code>setx VCPKG_ROOT C:\\vcpkg
setx QT_DIR C:\\Qt\\6.11.0\\mingw_64
setx QT_MINGW_BIN C:\\Qt\\Tools\\mingw1310_64\\bin</code></pre>
          <strong>Then fully close Qt Creator and reopen it</strong> &mdash;
          <code>setx</code> only writes to the registry; the env vars only reach
          processes started <em>after</em> the change.  An already-running Qt
          Creator keeps the old (empty) environment.
        </li>
        <li><strong>Open the project &rarr; pick the kit
            <em>Desktop Qt 6.x MinGW 64-bit</em></strong>.  In the
            <em>Initial Configuration</em> panel, click <em>Add &rarr; String</em>
            and add these four entries (replace the project path with yours):
          <pre><code>CMAKE_TOOLCHAIN_FILE   = C:/vcpkg/scripts/buildsystems/vcpkg.cmake
VCPKG_TARGET_TRIPLET   = x64-mingw-qt
VCPKG_OVERLAY_TRIPLETS = C:/path/to/your/project/triplets
VCPKG_OVERLAY_PORTS    = C:/path/to/your/project/ports</code></pre>
          <ul>
            <li>Use forward slashes <code>/</code>, not back slashes
                <code>\\</code> (CMake interprets <code>\\Q</code> as an escape).</li>
            <li><strong>Use absolute paths for the overlay vars</strong>.
                Qt Creator&rsquo;s <em>Initial Configuration</em> does
                <strong>not</strong> expand <code>${sourceDir}</code> &mdash;
                that&rsquo;s a CMakePresets-only macro.  If you paste
                <code>${sourceDir}/triplets</code>, cmake gets it as a
                literal string, vcpkg can&rsquo;t find the
                <code>x64-mingw-qt</code> triplet, and manifest install
                fails before grpc/protobuf even start to compile.</li>
            <li>Make sure the var name is plural &mdash;
                <code>VCPKG_OVERLAY_TRIPLETS</code> (with S), not
                <code>VCPKG_OVERLAY_TRIPLET</code>.  vcpkg silently ignores
                the singular form.</li>
          </ul>
        </li>
        <li>Click <em>Configure Project</em>.  First configure: ~30&ndash;60 min while
            vcpkg compiles boringssl + abseil + protobuf + grpc + curl.  Subsequent
            configures: ~1&ndash;3 sec (cache hit).</li>
        <li><strong>If you've already configured once and it failed</strong>:
            <em>Build &rarr; Clear CMake Configuration</em>, then re-add the four
            <em>Initial Configuration</em> entries above and re-run <em>Run CMake</em>.
            Once <code>CMakeCache.txt</code> exists in the build dir, subsequent
            CMake runs do <strong>not</strong> re-pass <code>-D</code> flags &mdash;
            you must clear it to inject new vars.</li>
    </ol>

    <h3>Skip vcpkg install (use prebuilt)</h3>
    <ol>
        <li>Run <code>import_prebuilt.bat &lt;path&gt;.zip</code> from a terminal at
            project root (it auto-detects the Qt Creator build dir).</li>
        <li>In Qt Creator <em>Initial Configuration</em>, add
            <code>VCPKG_MANIFEST_INSTALL = OFF</code> (BOOL).</li>
        <li><em>Build &rarr; Clear CMake Configuration</em> &rarr; <em>Run CMake</em>.</li>
    </ol>

    <h3>Running the GUI from Qt Creator (F5) without copying DLLs</h3>
    <p>
      The build links the <code>.exe</code> against vcpkg DLLs in
      <code>build/&lt;cfg&gt;/vcpkg_installed/x64-mingw-qt/bin/</code>, plus
      Qt and MinGW runtime DLLs.  Windows&rsquo; DLL search only looks at the
      <code>.exe</code>&rsquo;s folder and <code>%PATH%</code>, so a fresh
      build run via F5 fails with <code>libprotobuf.dll not found</code>
      (or <code>Qt6Core.dll</code>, <code>libgcc_s_seh-1.dll</code>, etc.).
    </p>
    <p>
      Fix once per kit/preset: <em>Projects (Ctrl+5) &rarr; Run &rarr;
      Environment &rarr; Details &rarr;</em> select <code>Path</code> and
      click <em>Edit</em>.  Prepend (semicolon-separated) the three dirs
      below.  Use absolute paths; replace
      <code>&lt;build-dir&gt;</code> with this project&rsquo;s build dir
      shown in the <em>Build</em> tab (e.g. <code>build/Desktop_Qt_*-Debug</code>
      or <code>build-qt-vcpkg</code> for the preset):
    </p>
    <pre><code>&lt;build-dir&gt;\\vcpkg_installed\\x64-mingw-qt\\bin;C:\\Qt\\6.x.y\\mingw_64\\bin;C:\\Qt\\Tools\\mingw1310_64\\bin</code></pre>
    <p>
      For <strong>qt_client_grpcpp/</strong> (a separate sub-project with
      its own build dir), repeat the same edit on its
      <em>Run &rarr; Environment</em> &mdash; substituting its build dir.
      Re-doing this is only required when you change the build dir name
      (switch between Debug/Release, change kit, etc.); it survives
      rebuilds.
    </p>
    <p>
      <strong>Permanent alternative</strong>: run <code>deploy_qt_vcpkg.bat</code>
      (server) or <code>cd qt_client_grpcpp &amp;&amp; deploy_qt.bat</code>.
      Each script copies every DLL next to the <code>.exe</code> in
      <code>dist-qt-vcpkg/</code>; that folder is fully self-contained and
      runs without any PATH setup.  Useful when shipping a build to a
      teammate or to a test machine.
    </p>'''
    else:
        qtc_html = '''
    <ol>
        <li>Open <code>CMakeLists.txt</code>, choose the
            <strong>Desktop Qt 6.x MinGW</strong> kit, configure, build.  No
            vcpkg setup needed for the MSYS2 path.</li>
    </ol>'''

    # ---- Prebuilt libraries (download + use) ----
    prebuilt_html = ""
    if svc_uses_vcpkg or cli_uses_vcpkg:
        prebuilt_html = '''
        <p>
          To skip the 30&ndash;60 min vcpkg compile, download a teammate&rsquo;s
          prebuilt artifacts and import them.  Same triplet + same deps =
          binary-compatible across machines that have the same Qt MinGW.
        </p>
        <p>
          <strong>Download</strong>:
          <a href="https://bosch-my.sharepoint.com/:f:/p/ugc1hc/IgAuLLzLlXVnS6lFL3KREFfNAbw2m_51U7sqOkO8f-mnDrY?e=b43r9x"
             target="_blank">
            https://bosch-my.sharepoint.com/:f:/p/ugc1hc/IgAuLLzLlXVnS6lFL3KREFfNAbw2m_51U7sqOkO8f-mnDrY
          </a>
        </p>
        <p>
          Pick <code>vcpkg_installed_x64-mingw-qt.zip</code> (the installed
          tree, ~50&ndash;80&nbsp;MB after compression).  Save it anywhere.
        </p>

        <h3>Import via CLI</h3>
        <ol>
          <li>From the project root, run:
            <pre><code>import_prebuilt.bat C:\\path\\to\\vcpkg_installed_x64-mingw-qt.zip</code></pre>
            (or run <code>import_prebuilt.bat</code> with no arg for an
             interactive prompt).  The script extracts the zip into every
             build dir present in this project (server <code>build-qt-vcpkg/</code>,
             <code>qt_client_grpcpp/build/</code>, and any <code>build/Desktop_Qt_*/</code>
             from a previous Qt Creator run).</li>
          <li>Build with the prebuilt:
            <pre><code>set USE_PREBUILT_VCPKG=1
build_qt_vcpkg.bat</code></pre>
            <code>USE_PREBUILT_VCPKG=1</code> tells <code>build_qt_vcpkg.bat</code>
            to skip the <code>vcpkg install</code> step entirely AND pass
            <code>-DVCPKG_MANIFEST_INSTALL=OFF</code> to cmake (so the vcpkg
            toolchain doesn&rsquo;t try to re-install).  Build proceeds in
            ~30&nbsp;sec instead of 30&ndash;60 min.</li>
        </ol>

        <h3>Import via Qt Creator (preset flow &mdash; recommended)</h3>
        <ol>
          <li>If a full vcpkg compile is currently running, stop it:
              <em>Build &rarr; Cancel Build</em> (or the red Stop button on the
              bottom bar).</li>
          <li>Use the bundled <strong>vcpkg-x64-mingw-qt-prebuilt</strong>
              preset.  It already has <code>VCPKG_MANIFEST_INSTALL=OFF</code>
              and the right toolchain + overlays.
              <ul>
                <li>If the project was opened with the kit instead of the
                    preset: <em>File &rarr; Close Project</em>, delete
                    <code>CMakeLists.txt.user</code>, reopen
                    <code>CMakeLists.txt</code>, tick the
                    <strong>vcpkg-x64-mingw-qt-prebuilt</strong> preset on the
                    import dialog.</li>
              </ul>
          </li>
          <li>Click <em>Configure Project</em>.  It will fail at
              <code>find_package(gRPC)</code> &mdash; <strong>expected</strong>:
              <code>vcpkg_installed/</code> isn&rsquo;t populated yet, but the
              build dir is now created.</li>
          <li>From a terminal at project root, populate it:
              <pre><code>import_prebuilt.bat C:\\path\\to\\vcpkg_installed_x64-mingw-qt.zip</code></pre>
              The script auto-detects every build dir in the project &mdash;
              <code>build-qt-vcpkg/</code> (preset),
              <code>build/Desktop_Qt_*/</code> (any kit), and the client
              variants &mdash; and extracts to all of them.</li>
          <li>Back in Qt Creator: <em>Build &rarr; Run CMake</em>.  Should
              complete in ~1&ndash;3 sec.  Then <em>Build &rarr; Build All</em>.</li>
        </ol>

        <h3>Import via Qt Creator (kit flow)</h3>
        <p>
          If you tied debugger or run config to the
          <code>Desktop Qt 6.x MinGW 64-bit</code> kit and don&rsquo;t want
          to switch to the preset, do this instead:
        </p>
        <ol>
          <li>If a full vcpkg compile is currently running, stop it
              (<em>Build &rarr; Cancel Build</em>).</li>
          <li><em>Build &rarr; Clear CMake Configuration</em> (don&rsquo;t use
              <em>Clean</em> &mdash; it leaves <code>CMakeCache.txt</code>).</li>
          <li><em>Projects (Ctrl+5) &rarr; Build &rarr; Initial Configuration
              &rarr; Add &rarr; Boolean</em>:
              <pre><code>VCPKG_MANIFEST_INSTALL = OFF</code></pre>
              (or <em>Add &rarr; String</em> with value <code>OFF</code>; vcpkg
              parses both).  This tells the vcpkg toolchain &ldquo;don&rsquo;t
              run install &mdash; <code>vcpkg_installed/</code> is already
              populated.&rdquo;  Without this, vcpkg will overwrite your
              imported tree.</li>
          <li>Click <em>Run CMake</em>.  It will fail at
              <code>find_package(gRPC)</code> &mdash; expected; the build dir
              is now created.</li>
          <li>From a terminal at project root, populate
              <code>vcpkg_installed/</code>:
              <pre><code>import_prebuilt.bat C:\\path\\to\\vcpkg_installed_x64-mingw-qt.zip</code></pre>
              Verify extract worked:
              <pre><code>dir build\\Desktop_Qt_*\\vcpkg_installed\\x64-mingw-qt\\share\\grpc\\</code></pre>
              should list <code>gRPCConfig.cmake</code>.</li>
          <li>Back in Qt Creator: <em>Build &rarr; Run CMake</em> &rarr;
              completes in ~1&ndash;3 sec.  Then <em>Build &rarr; Build All</em>.</li>
        </ol>

        <h3>Verify it really used the prebuilt</h3>
        <p>In <em>General Messages</em> after configure succeeds, you should
           see:</p>
        <pre><code>-- The CXX compiler identification is GNU 13.1.0
-- Found gRPC: &lt;build-dir&gt;/vcpkg_installed/x64-mingw-qt/share/grpc
-- Found Protobuf: ...
-- Configuring done (X.Xs)</code></pre>
        <p>You should <strong>not</strong> see lines like:</p>
        <pre><code>-- Building boringssl[core]:x64-mingw-qt...
-- Building abseil[core]:x64-mingw-qt...</code></pre>
        <p>If you do, <code>VCPKG_MANIFEST_INSTALL=OFF</code> didn&rsquo;t reach
           the toolchain &mdash; check <em>Initial Configuration</em> still has
           the entry, then <em>Clear CMake Configuration</em> + <em>Run CMake</em>
           again.</p>

        <p>
          <strong>Where the zip lands</strong>: <code>import_prebuilt.bat</code>
          extracts into every detected build dir&rsquo;s <code>vcpkg_installed/</code>
          subfolder.  Each gets its own copy (~184&nbsp;MB unpacked) so the
          server, console+widget client, and qt_client_grpcpp can all build
          independently against the same artifacts.
        </p>

        <p>
          <strong>Sharing your own prebuilt back</strong>: after a successful
          local build, run <code>export_prebuilt.bat</code> to pack
          <code>build-qt-vcpkg/vcpkg_installed/x64-mingw-qt/</code> +
          <code>x64-windows/tools/grpc/</code> into
          <code>prebuilt/vcpkg_installed_x64-mingw-qt.zip</code>.  Upload to
          the shared SharePoint folder so other devs save the rebuild cost.
        </p>'''

    # ---- Run sequence ----
    # Build Nomad job table per service so user has copy-pasteable commands.
    nomad_rows = "\n".join(
        f'        <tr><td><code>{s.name}</code></td>'
        f'<td><pre><code>nomad job run deploy\\{_mono_snake(s.name)}.nomad.hcl</code></pre></td>'
        f'<td><pre><code>nomad job stop {_mono_snake(s.name)}</code></pre></td></tr>'
        for s in services
    )
    run_html = f'''
        <h3>1. Start the agents (one-time per dev session)</h3>
        <p>Open two terminals and leave them running.</p>
        <p><strong>Terminal A &mdash; Consul</strong>:</p>
        <pre><code>consul agent -dev -client=0.0.0.0 -ui</code></pre>
        <p>UI at <a href="http://127.0.0.1:8500" target="_blank">http://127.0.0.1:8500</a>.
           Sanity check: <code>consul members</code> &mdash; should list one alive member.</p>

        <p><strong>Terminal B &mdash; Nomad</strong>:</p>
        <p>Windows needs <code>raw_exec</code> driver enabled.  Create
           <code>C:\\nomad\\dev.hcl</code> once with:</p>
        <pre><code>plugin "raw_exec" {{
  config {{
    enabled = true
  }}
}}</code></pre>
        <p>Then start the agent:</p>
        <pre><code>nomad agent -dev -config=C:\\nomad\\dev.hcl</code></pre>
        <p>UI at <a href="http://127.0.0.1:4646" target="_blank">http://127.0.0.1:4646</a>.
           Sanity check: <code>nomad node status</code>.</p>

        <h3>2. One-time setup: resolve absolute paths in HCL files</h3>
        <p>Generated <code>deploy\\*.nomad.hcl</code> files use a
           <code>C:/path/to/&lt;project&gt;</code> placeholder.  Run this script
           once after scaffold (or after moving the project folder):</p>
        <pre><code>prep_nomad_paths.bat</code></pre>
        <p>This rewrites every <code>.hcl</code> file to point at the
           current project&rsquo;s absolute path.  Idempotent.</p>

        <h3>3. Submit each service to Nomad</h3>
        <p>Pick the dist folder matching your build path:</p>
        <ul>
          <li>MSYS2 build: HCL points at <code>dist-msys2\\run_&lt;service&gt;.bat</code></li>
          <li>vcpkg build (after <code>deploy_qt_vcpkg.bat</code>): the
              <code>dist-qt-vcpkg\\</code> copy of the HCL points at
              <code>dist-qt-vcpkg\\run_&lt;service&gt;.bat</code> instead.
              Submit those from <code>dist-qt-vcpkg\\deploy\\</code>.</li>
        </ul>
        <p>Submit each job:</p>
        <table>
          <tr><th>Service</th><th>Submit</th><th>Stop</th></tr>
{nomad_rows}
        </table>
        <p>After submission, Nomad picks a random free port (defined as
           <code>port "grpc" {{ }}</code> in the HCL) and exports it as
           <code>${{NOMAD_PORT_grpc}}</code> &rarr; the service reads it from
           <code>&lt;PREFIX&gt;_GRPC_PORT</code> env var and registers in
           Consul under that port.</p>

        <h3>4. Verify each service is up</h3>
        <pre><code>nomad job status &lt;service&gt;
consul catalog services
curl http://127.0.0.1:8500/v1/health/service/&lt;service&gt;?passing=true</code></pre>
        <p>The Consul query returns the resolved <code>host:port</code> the
           UI client uses when <strong>Use Consul</strong> is checked.</p>

        <h3>5. Tail logs / stop / restart</h3>
        <pre><code>nomad alloc logs &lt;alloc-id&gt;        :: stream stdout/stderr
nomad job stop &lt;service&gt;            :: deregister + kill
nomad job run deploy\\&lt;service&gt;.nomad.hcl  :: re-submit</code></pre>
        <p>Get the alloc ID from <code>nomad job status &lt;service&gt;</code>.</p>

        <h3>Direct launch (skip Nomad)</h3>
        <p>Useful for quick smoke tests &mdash; the service still registers
           with Consul if <code>CONSUL_ADDR</code> is reachable:</p>
        <pre><code>set &lt;PREFIX&gt;_GRPC_PORT=50051
dist-qt-vcpkg\\run_&lt;service&gt;.bat</code></pre>
        <p>(Replace <code>&lt;PREFIX&gt;</code> with the env prefix listed in
           the &ldquo;Project at a glance&rdquo; table.)</p>'''

    # ---- Troubleshooting ----
    trouble_items = []
    if svc_uses_vcpkg or cli_uses_vcpkg:
        trouble_items.append((
            'Qt Creator: <code>Could not find a package configuration file provided by &quot;gRPC&quot;</code>',
            '<p>Symptom (kit-based flow, <code>build/Desktop_Qt_*-Debug/</code>):</p>'
            '<pre><code>CMake Error at CMakeLists.txt:60 (find_package):\n'
            '  Could not find a package configuration file provided by &quot;gRPC&quot; ...\n'
            '  Add the installation prefix of &quot;gRPC&quot; to CMAKE_PREFIX_PATH ...</code></pre>'
            '<p>The cmake invocation has no <code>-DCMAKE_TOOLCHAIN_FILE=...</code> flag, '
            'so vcpkg never loads, and the manifest install never runs.  Two fixes:</p>'
            '<p><strong>Fix A (recommended): switch to the preset.</strong>  Close the '
            'project, reopen via <em>File &rarr; Open File or Project &rarr; '
            'CMakeLists.txt</em> and select the <code>vcpkg-x64-mingw-qt</code> preset '
            'on the import dialog.</p>'
            '<p><strong>Fix B: stay on the kit, but inject toolchain vars manually.</strong></p>'
            '<ol>'
            '<li><em>Build &rarr; Clear CMake Configuration</em> (<em>Clean</em> alone '
            'does NOT clear cache).</li>'
            '<li><em>Projects (Ctrl+5) &rarr; Build &rarr; Initial Configuration &rarr; '
            'Add &rarr; String</em> and add all four (replace placeholders with '
            'your vcpkg checkout and project absolute paths):'
            '<pre><code>CMAKE_TOOLCHAIN_FILE   = C:/vcpkg/scripts/buildsystems/vcpkg.cmake\n'
            'VCPKG_TARGET_TRIPLET   = x64-mingw-qt\n'
            'VCPKG_OVERLAY_TRIPLETS = C:/path/to/your/project/triplets\n'
            'VCPKG_OVERLAY_PORTS    = C:/path/to/your/project/ports</code></pre>'
            '<strong>Pitfalls:</strong>'
            '<ul>'
            '<li>Use absolute paths for overlay vars &mdash; Qt Creator '
            'does <strong>not</strong> expand <code>${sourceDir}</code> '
            'in <em>Initial Configuration</em> (CMakePresets-only macro).  '
            'Literal <code>${sourceDir}/triplets</code> reaches vcpkg, which '
            'can&rsquo;t find <code>x64-mingw-qt.cmake</code> and aborts '
            'manifest install.</li>'
            '<li>Var name is <strong>plural</strong>: '
            '<code>VCPKG_OVERLAY_TRIPLETS</code> (with S).  Singular '
            '<code>VCPKG_OVERLAY_TRIPLET</code> is silently ignored.</li>'
            '<li>Forward slashes only.  <code>\\</code> triggers <code>Invalid '
            'character escape \\Q</code>.</li>'
            '</ul>'
            '</li>'
            '<li>Click <em>Run CMake</em>.</li>'
            '</ol>'
            '<p>Why the autodetect in <code>CMakeLists.txt</code> didn&rsquo;t fire: '
            'it reads <code>$ENV{VCPKG_ROOT}</code>.  If you ran <code>setx VCPKG_ROOT</code> '
            '<em>after</em> Qt Creator was launched, the var isn&rsquo;t in its '
            'environment &mdash; the warning prints, but the toolchain stays unset '
            'and <code>find_package(gRPC)</code> fails.</p>'))
        trouble_items.append((
            'vcpkg <code>BUILD_FAILED</code> on grpc with gcc 13 ICE',
            'The overlay-port at <code>ports/grpc/</code> includes patch '
            '<code>00018-gcc13-per-cpu-ice-workaround.patch</code>.  '
            'If it didn&rsquo;t apply, delete <code>ports/grpc/portfile.cmake</code> '
            'and re-run <code>init_vcpkg_overlay.bat</code>.'))
        trouble_items.append((
            '<code>Could NOT find Protobuf (missing: Protobuf_PROTOC_EXECUTABLE)</code>',
            'CMakeLists pre-sets <code>Protobuf_PROTOC_EXECUTABLE</code> to '
            '<code>build/.../vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe</code>.  '
            'If your zip doesn&rsquo;t have host tools, run '
            '<code>export_prebuilt.bat</code> from a fully-built dir to pack '
            '<code>x64-windows/tools/grpc/</code> too.'))
        trouble_items.append((
            'Linker error <code>-ignore:4221 unrecognized</code>',
            'find_package picked vcpkg&rsquo;s MSVC <code>x64-windows</code> libs '
            'instead of our MinGW <code>x64-mingw-qt</code>.  Wipe the build dir '
            '(<code>rmdir /s /q build\\Desktop_Qt_*</code>) and re-configure.'))
        trouble_items.append((
            '<code>Could not find _grpc_cpp using ... grpc_cpp_plugin.exe</code>',
            'Host tools missing.  Copy <code>x64-windows/tools/grpc/</code> from '
            'a complete vcpkg_installed tree, or re-import a zip exported with '
            'the latest <code>export_prebuilt.bat</code> (it now packs host plugin).'))
        trouble_items.append((
            'CMake error <code>Invalid character escape \\Q</code>',
            'Stale <code>CMakeFiles\\&lt;ver&gt;\\CMakeCXXCompiler.cmake</code> '
            'from earlier failed configure.  Wipe the build dir entirely (Qt Creator '
            'Clean is not enough) and Run CMake.'))
        trouble_items.append((
            'Qt Creator: <code>vcpkg executable not found</code>',
            'Just a warning - the bundled <code>QT_CREATOR_SKIP_VCPKG_SETUP=ON</code> '
            'silences it.  If you still see it, ensure CMakeLists ran past <code>project()</code>.'))
        trouble_items.append((
            '<code>ninja: manifest \\&apos;build.ninja\\&apos; still dirty after 100 tries</code>',
            'Code-gen output landing in source tree.  Generated files use '
            '<code>${CMAKE_BINARY_DIR}/grpc_gen</code> by design - never change to source dir.'))
    if has_widget_gui or has_qt6_grpc_client or cli_uses_vcpkg:
        if cli_uses_vcpkg or svc_uses_vcpkg:
            trouble_items.append((
                'F5 in Qt Creator: <code>libprotobuf.dll</code> / '
                '<code>Qt6Core.dll</code> / <code>libgcc_s_seh-1.dll</code> not found',
                'Build dir holds only the <code>.exe</code> + import libs; the actual '
                'DLLs live in <code>build/&lt;cfg&gt;/vcpkg_installed/x64-mingw-qt/bin/</code> '
                '(vcpkg deps), <code>C:\\Qt\\6.x.y\\mingw_64\\bin\\</code> (Qt), and '
                '<code>C:\\Qt\\Tools\\mingw1310_64\\bin\\</code> (MinGW runtime).  '
                'Windows can&rsquo;t find them on F5.  Fix: <em>Projects (Ctrl+5) &rarr; '
                'Run &rarr; Environment &rarr; Details &rarr; Path &rarr; Edit</em>, '
                'prepend all three dirs (semicolon-separated).  See the &ldquo;Running '
                'the GUI from Qt Creator (F5)&rdquo; subsection for the full path string.  '
                'Or just run <code>deploy_qt.bat</code> / <code>deploy_qt_vcpkg.bat</code> '
                '&mdash; those copy every DLL next to the <code>.exe</code> in '
                '<code>dist-qt-vcpkg/</code>, no PATH hack needed.'))
        trouble_items.append((
            'GUI exe fails at startup with missing Qt DLL (deployed dist)',
            'Re-run the appropriate deploy script.  '
            '<code>windeployqt</code> auto-detects Debug vs Release from PE header; '
            'if it copied wrong variant, delete <code>dist-*</code> and re-run deploy.'))
    trouble_items.append((
        'Service starts but doesn&rsquo;t register in Consul',
        'Check <code>CONSUL_ADDR</code> env var (default <code>http://127.0.0.1:8500</code>).  '
        'In Nomad, set it via <code>env { ... }</code> in the .hcl, or set system-wide '
        'before running <code>build_deploy_*.bat</code>.'))
    trouble_items.append((
        'Service binds wrong port',
        'Each service reads <code>&lt;PREFIX&gt;_GRPC_PORT</code> (e.g. '
        f'<code>{_mono_snake(services[0].name).upper()}_GRPC_PORT</code>).  '
        'Nomad sets it from <code>${NOMAD_PORT_grpc}</code>; for direct launch, '
        'export the env var manually.'))
    trouble_items.append((
        'Qt Creator: <em>The ABI of the selected debugger does not match the toolchain ABI</em>',
        '<p>CMakePresets can pin compiler paths but has no field for a '
        'debugger.  Qt Creator&rsquo;s auto-imported preset kit pairs the '
        'MinGW compiler with whatever debugger it auto-detects (often MSVC '
        '<code>cdb.exe</code> or a system <code>gdb</code> with a different '
        'ABI), hence the warning.</p>'
        '<p><strong>One-time fix</strong> (per machine, not per project):</p>'
        '<ol>'
        '<li><em>Edit &rarr; Preferences &rarr; Kits &rarr; Debuggers</em> &mdash; '
        'verify there&rsquo;s an entry for '
        '<code>C:\\Qt\\Tools\\mingw1310_64\\bin\\gdb.exe</code>.  '
        'If not: <em>Add</em> &rarr; <em>Path</em> = that path, '
        '<em>Name</em> = <code>MinGW gdb (Qt 6.11)</code>.  <em>Apply</em>.</li>'
        '<li><em>Kits</em> tab &rarr; select the auto-imported kit named '
        'after the preset (e.g. <code>vcpkg + Qt MinGW 13.1.0 (Release)</code>) '
        '&rarr; set <em>Debugger</em> to the entry from step 1.  '
        '<em>Apply</em> + <em>OK</em>.</li>'
        '</ol>'
        '<p>The fix sticks across project re-imports because Qt Creator '
        'stores it in the kit, not the preset.  If Qt&rsquo;s installer '
        'already registered the bundled gdb (sometimes as '
        '<code>MinGW Debugger</code>), step 1 is unnecessary &mdash; pick '
        'the existing entry in step 2.</p>'))
    trouble_html = "\n".join(
        # Wrap simple text bodies in <p>; leave bodies that already start with a
        # block element (<p>, <pre>, <ol>, <ul>) alone so we don't nest them.
        '        <details><summary>{title}</summary>{wrapped}</details>'.format(
            title=title,
            wrapped=body if body.lstrip().startswith(('<p>', '<pre>', '<ol>', '<ul>'))
                         else f'<p>{body}</p>',
        )
        for title, body in trouble_items
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{proj} &mdash; Build &amp; Run Guide</title>
<style>
  :root {{
    --bg: #0f172a; --panel: #1e293b; --text: #e2e8f0; --muted: #94a3b8;
    --accent: #38bdf8; --green: #10b981; --amber: #fbbf24; --border: #334155;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0;
         background: var(--bg); color: var(--text); line-height: 1.65; }}
  header {{ background: linear-gradient(135deg, #0ea5e9, #6366f1);
            padding: 24px 30px 24px 280px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
  header h1 {{ margin: 0; font-size: 1.8em; text-shadow: 0 2px 4px rgba(0,0,0,0.4); }}
  header p {{ margin: 6px 0 0; opacity: 0.9; font-size: 0.95em; }}

  .sidebar-nav {{ position: fixed; top: 0; left: 0; width: 250px; height: 100vh;
                  background: #0b1220; border-right: 2px solid var(--border);
                  overflow-y: auto; padding: 20px 0; z-index: 200; }}
  .sidebar-nav .nav-title {{ padding: 0 20px 14px; font-size: 0.82em; font-weight: 700;
                             text-transform: uppercase; letter-spacing: 0.06em;
                             color: var(--muted); border-bottom: 1px solid var(--border);
                             margin-bottom: 8px; }}
  .sidebar-nav a {{ display: block; padding: 7px 20px; color: var(--muted);
                    text-decoration: none; font-size: 0.88em; font-weight: 500;
                    border-left: 3px solid transparent;
                    transition: color 0.15s, border-color 0.15s, background-color 0.15s; }}
  .sidebar-nav a:hover {{ color: var(--text); background: rgba(255,255,255,0.04); }}
  .sidebar-nav a.active {{ color: var(--accent); border-left-color: var(--accent);
                           background: rgba(56,189,248,0.08); }}
  .sidebar-nav .nav-group {{ margin-top: 14px; padding: 0 20px 4px; font-size: 0.72em;
                             font-weight: 700; text-transform: uppercase;
                             letter-spacing: 0.05em; color: rgba(148,163,184,0.6); }}

  main {{ margin-left: 250px; padding: 28px 38px; max-width: 1400px; }}
  section {{ background: var(--panel); border-radius: 12px; padding: 22px 26px;
             margin-bottom: 22px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
             border-left: 4px solid var(--accent); }}
  section h2 {{ color: var(--accent); margin-top: 0; border-bottom: 1px solid var(--border);
                padding-bottom: 10px; font-size: 1.3em; }}
  h3 {{ color: var(--amber); margin-top: 18px; }}
  code {{ background: #0b1220; padding: 2px 6px; border-radius: 4px; color: #fcd34d;
          font-family: "Cascadia Code", "Fira Code", Consolas, monospace; font-size: 0.9em; }}
  pre {{ background: #0b1220; padding: 14px 14px 14px 14px; border-radius: 8px;
         overflow-x: auto; border: 1px solid var(--border); font-size: 0.88em;
         position: relative; }}
  pre code {{ background: none; padding: 0; color: var(--text); }}
  pre .copy-btn {{ position: absolute; top: 6px; right: 6px; background: #1e293b;
                   border: 1px solid var(--border); color: var(--muted); padding: 3px 10px;
                   font-size: 0.75em; border-radius: 4px; cursor: pointer; opacity: 0;
                   transition: opacity 0.15s, color 0.15s, background 0.15s;
                   font-family: -apple-system, "Segoe UI", Roboto, sans-serif; }}
  pre:hover .copy-btn {{ opacity: 1; }}
  pre .copy-btn:hover {{ color: var(--text); background: #334155; }}
  pre .copy-btn.copied {{ color: var(--green); border-color: var(--green); }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0;
           background: rgba(0,0,0,0.2); border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border);
            font-size: 0.92em; vertical-align: top; }}
  th {{ background: #0b1220; color: var(--accent); }}
  tr:last-child td {{ border-bottom: none; }}
  details {{ background: rgba(251,191,36,0.06); border-left: 3px solid var(--amber);
             padding: 8px 14px; border-radius: 6px; margin: 8px 0; }}
  details summary {{ cursor: pointer; font-weight: 600; color: var(--amber); }}
  details p {{ margin: 8px 0 4px; }}
  a {{ color: var(--accent); }}

  /* Responsive: collapse sidebar on narrow viewports.  The page becomes
     full-width and the sidebar is dismissed; user can still navigate via
     the in-page Quick reference table or browser scroll. */
  @media (max-width: 900px) {{
    .sidebar-nav {{ display: none; }}
    header {{ padding-left: 30px; }}
    main {{ margin-left: 0; padding: 20px; }}
  }}
</style>
</head>
<body>
<script>
  // Add copy buttons to every <pre> block on load.  Uses the modern
  // navigator.clipboard API, falls back to a textarea + execCommand for
  // older browsers (or file:// where clipboard API is sandboxed).
  document.addEventListener('DOMContentLoaded', () => {{
    document.querySelectorAll('pre').forEach((pre) => {{
      const btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.type = 'button';
      btn.textContent = 'Copy';
      btn.addEventListener('click', async () => {{
        const text = pre.querySelector('code') ? pre.querySelector('code').innerText : pre.innerText;
        let ok = false;
        try {{
          if (navigator.clipboard && window.isSecureContext) {{
            await navigator.clipboard.writeText(text);
            ok = true;
          }} else {{
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed'; ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            ok = document.execCommand('copy');
            document.body.removeChild(ta);
          }}
        }} catch (e) {{ ok = false; }}
        btn.textContent = ok ? 'Copied!' : 'Failed';
        btn.classList.toggle('copied', ok);
        setTimeout(() => {{
          btn.textContent = 'Copy';
          btn.classList.remove('copied');
        }}, 1500);
      }});
      pre.appendChild(btn);
    }});

    // Sidebar: highlight the active section as the user scrolls.  Uses
    // IntersectionObserver so it stays cheap on long pages.
    const links = document.querySelectorAll('.sidebar-nav a[href^="#"]');
    const sections = Array.from(links)
      .map(a => document.getElementById(a.getAttribute('href').slice(1)))
      .filter(Boolean);
    if ('IntersectionObserver' in window && sections.length) {{
      const linkFor = (id) => document.querySelector('.sidebar-nav a[href="#' + id + '"]');
      const setActive = (id) => {{
        links.forEach(a => a.classList.remove('active'));
        const a = linkFor(id);
        if (a) a.classList.add('active');
      }};
      const observer = new IntersectionObserver((entries) => {{
        const visible = entries.filter(e => e.isIntersecting)
                               .sort((a, b) => a.target.offsetTop - b.target.offsetTop);
        if (visible.length) setActive(visible[0].target.id);
      }}, {{ rootMargin: '-30% 0px -60% 0px', threshold: 0 }});
      sections.forEach(s => observer.observe(s));
    }}
  }});
</script>
<header>
  <h1>{proj}</h1>
  <p>Build &amp; run guide.  Auto-generated by <code>mb-scaffold</code>.</p>
</header>

<nav class="sidebar-nav">
  <div class="nav-title">{proj}</div>
  <a href="#overview">Project at a glance</a>
  <a href="#quick-ref">Quick reference</a>
  <a href="#folder-structure">Folder structure</a>
  <a href="#flow">Build &amp; run flow</a>
  <a href="#prereqs">Prerequisites</a>
  <a href="#framework-dep">Framework dependency (MicroserviceBase)</a>

  <div class="nav-group">Setup</div>
  <a href="#env-setup">Environment setup</a>
  {'<a href="#rationale">How vcpkg + Qt MinGW works</a>' if (svc_uses_vcpkg or cli_uses_vcpkg) else ''}

  <div class="nav-group">Build</div>
  <a href="#cli-build">Build via CLI</a>
  <a href="#qtc-build">Build in Qt Creator</a>
  {'<a href="#prebuilt">Use prebuilt libraries</a>' if (svc_uses_vcpkg or cli_uses_vcpkg) else ''}

  <div class="nav-group">Run</div>
  <a href="#run">Consul + Nomad</a>

  <div class="nav-group">Help</div>
  <a href="#troubleshooting">Common issues &amp; fixes</a>
  <a href="#see-also">See also</a>
</nav>

<main>

  <section id="overview">
    <h2>Project at a glance</h2>
    <table>
      <tr><th>Service</th><th>Methods</th><th>Env prefix</th></tr>
{svc_rows}
    </table>
    <p>Server toolchain: <code>{spec.server_grpc_kind}</code>.  Client variant:
       <code>{spec.client_grpc_kind}</code>.  GUI: <code>{spec.gui_type}</code>.</p>
  </section>

  <section id="quick-ref">
    <h2>Quick reference</h2>
    <table>
      <tr><th>Task</th><th>Command (run from project root)</th></tr>
{quick_rows}
    </table>
  </section>

  <section id="folder-structure">
    <h2>Folder structure</h2>
    <p><code>[edit]</code> marks files you'll write business logic into.
       Everything else is scaffolding regenerated by <code>mb-scaffold</code>
       &mdash; safe to leave alone.</p>
    <pre><code>{proj}/
&#9500;&#9472;&#9472; proto/{spec.snake_name}.proto     # one shared .proto for all services
&#9500;&#9472;&#9472; src/&lt;service_snake&gt;/              # one folder per service
&#9474;   &#9500;&#9472;&#9472; main.cpp                      # ServiceRunner entry-point
&#9474;   &#9500;&#9472;&#9472; domain/&lt;Service&gt;.{{h,cpp}}      # [edit] business logic (pure C++)
&#9474;   &#9492;&#9472;&#9472; adapters/api/&lt;Service&gt;GrpcAdapter.{{h,cpp}}  # [edit] proto&lt;-&gt;domain wrapper
&#9500;&#9472;&#9472; deploy/&lt;service_snake&gt;.nomad.hcl  # one Nomad job per service
&#9500;&#9472;&#9472; client/                           # console client subproject
&#9500;&#9472;&#9472; CMakeLists.txt                    # single project, N add_executable() calls
&#9500;&#9472;&#9472; build_deploy.bat / .sh            # one-shot build for all services
&#9500;&#9472;&#9472; set_env*.bat / .sh                # toolchain env (VCPKG_ROOT, QT_DIR, ...)
&#9492;&#9472;&#9472; dist/                             # output: N .exe&#39;s + shared DLLs</code></pre>
  </section>

  <section id="flow">
    <h2>Build &amp; run flow</h2>
    <p>Pick a toolchain on first build; subsequent rebuilds skip the
       slow vcpkg compile (cache hit ~1&ndash;3 min).  See the
       &quot;Use prebuilt libraries&quot; section if a teammate already
       compiled the deps and shared a zip.</p>
    <div class="mermaid">
flowchart TD
    Start([Start])
    Setup["1\. One-time setup<br/>setx VCPKG_ROOT, QT_DIR, QT_MINGW_BIN"]
    Choose{{"Toolchain?"}}
    Prebuilt{{"Have prebuilt zip?"}}
    Import["import_prebuilt.bat &lt;zip&gt;<br/>~30 seconds"]
    BuildVcpkg["build_qt_vcpkg.bat<br/>(or Qt Creator F5)"]
    BuildMSYS2["build_deploy_msys2.bat"]
    BuildResult["build*/&lt;service&gt;.exe<br/>(N executables) + DLLs"]
    LocalRun["Run any service:<br/>./&lt;service&gt;.exe"]
    Pkg["deploy_qt_vcpkg.bat<br/>&rarr; dist-qt-vcpkg/"]
    NomadRun["nomad job run<br/>deploy/&lt;svc&gt;.nomad.hcl<br/>(per-service jobs)"]
    Discover["Clients discover via Consul<br/>(one entry per service)"]

    Start --> Setup --> Choose
    Choose -->|"Qt MinGW + vcpkg<br/>(recommended)"| Prebuilt
    Choose -->|MSYS2| BuildMSYS2 --> BuildResult
    Prebuilt -->|"Yes (~2 min total)"| Import --> BuildVcpkg
    Prebuilt -->|"No (first build ~30-60 min)"| BuildVcpkg
    BuildVcpkg --> BuildResult
    BuildResult --> LocalRun
    BuildResult -->|For sharing| Pkg
    LocalRun --> NomadRun
    Pkg --> NomadRun
    NomadRun --> Discover
    </div>
  </section>

{full_kit_walkthrough_html}

  <section id="prereqs">
    <h2>Prerequisites</h2>
    <ul>
{prereq_html}
    </ul>
  </section>

  <section id="framework-dep">
    <h2>Framework dependency (MicroserviceBase)</h2>
    <p>
      This service depends on the <strong>MicroserviceBase</strong> runtime
      (C++ library + CMake package).  <code>CMakeLists.txt</code> calls
      <code>find_package(MicroserviceBase CONFIG)</code> first and falls
      back to <code>add_subdirectory(.../MicroserviceBase/runtime_cpp)</code>
      for in-tree builds.  Pick one of three setups (any satisfies the
      dependency):
    </p>
    <table>
      <tr><th>Setup</th><th>When to use</th><th>One-time steps</th></tr>
      <tr>
        <td><strong>A. In-tree (zero install)</strong></td>
        <td>You&rsquo;re working inside the framework checkout</td>
        <td>Clone the framework so this scaffold sits at
            <code>&lt;framework&gt;/examples/&lt;svc&gt;/</code> &mdash;
            the relative path
            <code>../../MicroserviceBase/runtime_cpp</code> resolves
            automatically.</td>
      </tr>
      <tr>
        <td><strong>A2. <code>MICROSERVICEBASE_DIR</code> env var</strong></td>
        <td>Scaffold lives anywhere outside <code>examples/</code></td>
        <td><code>setx MICROSERVICEBASE_DIR D:\\workspace\\python-microservice-base</code>
            (accepts the framework root, the <code>runtime_cpp</code> parent,
            or <code>runtime_cpp</code> itself).  Qt Creator inherits user
            env so it picks this up automatically &mdash; close + reopen
            Qt Creator after <code>setx</code>.</td>
      </tr>
      <tr>
        <td><strong>B. CMake install</strong></td>
        <td>Standalone service, no vcpkg</td>
        <td><code>cmake -S &lt;framework&gt;/MicroserviceBase/runtime_cpp -B build/mb &amp;&amp; cmake --build build/mb &amp;&amp; cmake --install build/mb --prefix $HOME/.local/microservice-base</code>,
            then pass
            <code>-DCMAKE_PREFIX_PATH=$HOME/.local/microservice-base</code>
            on configure.</td>
      </tr>
      <tr>
        <td><strong>C. vcpkg overlay-port</strong></td>
        <td>Already using vcpkg (the Qt+vcpkg path)</td>
        <td>Add <code>microservice-base</code> to your
            <code>vcpkg.json</code> <code>dependencies</code> and pass
            <code>-DVCPKG_OVERLAY_PORTS=&lt;framework&gt;/ports</code>.</td>
      </tr>
    </table>
    <p>
      <strong>Get the framework</strong> &mdash; branch
      <code>ugc1hc/feat/migrate_to_ta_architecture</code> is the current
      TA-architecture line (gRPC + Consul + Nomad runtime this scaffold
      targets):
    </p>
    <pre><code>git clone -b ugc1hc/feat/migrate_to_ta_architecture ^
    https://github.com/test-fullautomation/python-microservice-base.git</code></pre>
    <p>What you get:</p>
    <ul>
      <li><code>MicroserviceBase/runtime_cpp/</code> &mdash; C++ runtime,
          used by setups A, B, C.</li>
      <li><code>ports/microservice-base/</code> &mdash; vcpkg overlay-port
          for setup C.</li>
      <li><code>docs/runtime_cpp_install.md</code> &mdash; full instructions
          for each setup.</li>
    </ul>
    <p>
      If <code>cmake -S .</code> fails with
      <code>MicroserviceBase runtime not found.  Install + add to
      CMAKE_PREFIX_PATH</code>, that&rsquo;s this dependency missing &mdash;
      pick a setup above.
    </p>
  </section>

  <section id="env-setup">
    <h2>Environment setup (one-time)</h2>
{_readme_env_section_html(svc_uses_vcpkg or cli_uses_vcpkg, has_qt6_grpc_client)}
  </section>

  <section id="rationale">
    <h2>How vcpkg + Qt MinGW works</h2>
{rationale_html if rationale_html else '    <p>This scaffold uses MSYS2&rsquo;s prebuilt grpc/protobuf - see <code>examples/docs/html/mingw_setup.html</code> for the toolchain story.</p>'}
  </section>

  <section id="cli-build">
    <h2>Build via CLI (no Qt Creator)</h2>
    <ol>
{cli_html}
    </ol>
    <p>
      All scripts are runnable from the project root.  They use
      <code>%~dp0</code>-relative paths internally so they work regardless
      of where you call them from.
    </p>
  </section>

  <section id="qtc-build">
    <h2>Build &amp; run in Qt Creator</h2>
{qtc_html}
  </section>

{('<section id="prebuilt"><h2>Use prebuilt libraries (skip the 30-60 min vcpkg compile)</h2>' + prebuilt_html + '</section>') if prebuilt_html else ''}

  <section id="run">
    <h2>Run sequence (Consul + Nomad)</h2>
{run_html}
  </section>

  <section id="troubleshooting">
    <h2>Common issues &amp; fixes</h2>
    <p>Click each entry to expand.</p>
{trouble_html}
  </section>

  <section id="see-also">
    <h2>See also</h2>
    <ul>
      <li><code>README.md</code> &mdash; same content as plain Markdown.</li>
      <li><code>examples/docs/html/index.html</code> &mdash; framework-level
          docs (toolchain matrix, vcpkg setup, MSYS2 setup).</li>
      <li><code>vcpkg_setup.html</code> in the framework docs &mdash; the
          <code>google_vcpkg</code> path explained in depth.</li>
    </ul>
  </section>

</main>

<!-- Mermaid for the build/run flow diagram in #flow.  Loaded from the
     framework-level docs/js/mermaid.min.js if available (zero-cost when
     missing -- diagrams just render as their source code instead). -->
<script src="../../docs/js/mermaid.min.js"></script>
<script>
  if (typeof mermaid !== 'undefined') {{
    mermaid.initialize({{
      startOnLoad: true, theme: 'dark', securityLevel: 'loose',
      flowchart: {{ htmlLabels: true, useMaxWidth: true }}
    }});
  }}
</script>

</body>
</html>
'''


def _mono_readme(spec, services) -> str:
    svc_lines = "\n".join(
        f"- **{s.name}** — {len(s.methods)} method(s), env prefix `{_mono_snake(s.name).upper()}_`"
        for s in services
    )
    svc_uses_vcpkg = spec.server_grpc_kind == "vcpkg"
    cli_uses_vcpkg = (spec.gui_type != "none"
                     and spec.client_grpc_kind == "google_vcpkg")
    full_kit_walkthrough_md = ""
    if svc_uses_vcpkg and cli_uses_vcpkg:
        full_kit_walkthrough_md = '''

## Full step-by-step: load both projects in Qt Creator with `Desktop Qt 6.x MinGW 64-bit`, no rebuild

The fastest path that loads **both** the server and the
`qt_client_grpcpp/` client into Qt Creator using the kit (no preset, no
30–60 min vcpkg compile).  Follow exactly.

### One-time setup

1. Set system env vars in CMD (replace paths if different):

   ```cmd
   setx VCPKG_ROOT C:\\vcpkg
   setx QT_DIR C:\\Qt\\6.11.0\\mingw_64
   setx QT_MINGW_BIN C:\\Qt\\Tools\\mingw1310_64\\bin
   ```

2. **Fully close Qt Creator** (kill stray `qtcreator.exe` in Task
   Manager).  `setx` only reaches future processes.
3. Download `vcpkg_installed_x64-mingw-qt.zip` from the SharePoint link
   (in `README.html`, section "Use prebuilt libraries").  Save anywhere,
   e.g. `C:\\prebuilt\\vcpkg_installed_x64-mingw-qt.zip`.

### Step 1 — configure the server project

1. Open Qt Creator → *File → Open File or Project* → this project's
   `CMakeLists.txt`.
2. Configure dialog: **untick every preset**.  Tick only
   `Desktop Qt 6.x MinGW 64-bit`.  Click *Configure Project*.
3. If a long vcpkg compile starts, *Build → Cancel Build*.
4. *Build → Clear CMake Configuration* (NOT *Clean*).
5. *Projects (Ctrl+5) → Build → Initial Configuration → Add* — five
   entries (replace placeholders with your absolute paths):

   | Type    | Name                     | Value                                                       |
   |---------|--------------------------|-------------------------------------------------------------|
   | String  | `CMAKE_TOOLCHAIN_FILE`   | `C:/vcpkg/scripts/buildsystems/vcpkg.cmake`                 |
   | String  | `VCPKG_TARGET_TRIPLET`   | `x64-mingw-qt`                                              |
   | String  | `VCPKG_OVERLAY_TRIPLETS` | `C:/path/to/your/project/triplets`                          |
   | String  | `VCPKG_OVERLAY_PORTS`    | `C:/path/to/your/project/ports`                             |
   | Boolean | `VCPKG_MANIFEST_INSTALL` | `OFF`                                                       |

   - Var name is **plural**: `VCPKG_OVERLAY_TRIPLETS` (with S).
   - Use **absolute paths** for overlay vars; Qt Creator does not
     expand `${sourceDir}` in *Initial Configuration*.
   - Forward slashes only (`/`, not `\\`).
   - `VCPKG_MANIFEST_INSTALL=OFF` is what skips the rebuild.  Without
     it, vcpkg overwrites the prebuilt tree.
6. *Build → Run CMake*.  Will fail at `find_package(gRPC)` — expected;
   the build dir is now created.

### Step 2 — configure the qt_client_grpcpp project

1. *File → Open File or Project* → `qt_client_grpcpp\\CMakeLists.txt`
   (separate sub-project, separate build dir).
2. Configure dialog: untick every preset, tick only
   `Desktop Qt 6.x MinGW 64-bit`.
3. Cancel any vcpkg compile, *Clear CMake Configuration*.
4. *Initial Configuration* → same five entries as Step 1.  Both overlay
   paths still point at the **parent** `triplets/` and `ports/` (one
   level up from `qt_client_grpcpp/`).
5. *Run CMake*.  Fails at `find_package(Protobuf)` — expected.

### Step 3 — populate `vcpkg_installed/` from the prebuilt zip

1. Open CMD at the **parent project** root (this dir):

   ```cmd
   cd /d C:\\path\\to\\your\\project
   ```

2. Import once — auto-detects every build dir (server + qt_client_grpcpp)
   and extracts to all:

   ```cmd
   import_prebuilt.bat C:\\prebuilt\\vcpkg_installed_x64-mingw-qt.zip
   ```

3. Verify:

   ```cmd
   dir build\\Desktop_Qt_*\\vcpkg_installed\\x64-mingw-qt\\share\\grpc\\
   dir qt_client_grpcpp\\build\\Desktop_Qt_*\\vcpkg_installed\\x64-mingw-qt\\share\\grpc\\
   ```

   Both should list `gRPCConfig.cmake`.

### Step 4 — re-run CMake on both projects

1. Server project → *Build → Run CMake*.  Should finish in 1–3 sec:

   ```
   -- Found gRPC: <build-dir>/vcpkg_installed/x64-mingw-qt/share/grpc
   -- Found Protobuf: ...
   -- Configuring done
   ```

2. qt_client_grpcpp project → *Build → Run CMake*.  Same.
3. *Build → Build All* on both.  Project code compiles in 30 sec – 2 min;
   vcpkg deps are NOT rebuilt.

### Sanity check: did it really skip the rebuild?

You should **not** see lines like:

```
-- Building boringssl[core]:x64-mingw-qt...
-- Building abseil[core]:x64-mingw-qt...
-- Building grpc:x64-mingw-qt...
```

If you do, `VCPKG_MANIFEST_INSTALL=OFF` didn't reach the toolchain —
verify the entry is still in *Initial Configuration*, then
*Clear CMake Configuration* + *Run CMake*.
'''

    qtc_section = ""
    if svc_uses_vcpkg or cli_uses_vcpkg:
        qtc_section = '''

## Build in Qt Creator (Desktop Qt 6.x MinGW 64-bit kit)

**Recommended**: import the project via the bundled `vcpkg-x64-mingw-qt`
preset (Qt Creator detects `CMakePresets.json` automatically).  The preset
already has `CMAKE_TOOLCHAIN_FILE`, `VCPKG_TARGET_TRIPLET`, and overlays
baked in — no manual wiring.

**If you must use the Qt kit instead of the preset**, Qt Creator does *not*
auto-detect vcpkg.  Tell it explicitly:

1. `setx VCPKG_ROOT C:\\vcpkg` (your vcpkg checkout) → **fully close and
   reopen Qt Creator** so the env var is in its process.
2. Open project → pick `Desktop Qt 6.x MinGW 64-bit` → in *Initial
   Configuration*, **Add → String** the four entries (replace the
   project path with yours):
   - `CMAKE_TOOLCHAIN_FILE = C:/vcpkg/scripts/buildsystems/vcpkg.cmake`
   - `VCPKG_TARGET_TRIPLET = x64-mingw-qt`
   - `VCPKG_OVERLAY_TRIPLETS = C:/path/to/your/project/triplets`
   - `VCPKG_OVERLAY_PORTS = C:/path/to/your/project/ports`

   Pitfalls:
   - Use **absolute paths** for the overlay vars. Qt Creator does *not*
     expand `${sourceDir}` in *Initial Configuration* (CMakePresets-only
     macro). Literal `${sourceDir}/triplets` reaches vcpkg → can't find
     `x64-mingw-qt.cmake` → manifest install aborts.
   - Var name is **plural**: `VCPKG_OVERLAY_TRIPLETS` (with S). Singular
     `VCPKG_OVERLAY_TRIPLET` is silently ignored.
   - Forward slashes `/` only — `\\` triggers CMake's `Invalid character
     escape \\Q` error.
3. Click *Configure Project*.

### Troubleshooting: `Could not find a package configuration file provided by "gRPC"`

If the cmake invocation has no `-DCMAKE_TOOLCHAIN_FILE=` flag, vcpkg never
loaded.  Two fixes:

- **Switch to the preset** (`vcpkg-x64-mingw-qt`) — quickest.
- **Stay on the kit**: *Build → Clear CMake Configuration*, then add the
  four `Initial Configuration` entries above, then *Run CMake*.  CMake
  caches the toolchain on first configure; subsequent runs do *not*
  re-pass `-D` flags, which is why a partially-configured build dir keeps
  failing even after you add the entries.

### Troubleshooting: `The ABI of the selected debugger does not match the toolchain ABI`

Qt Creator shows this warning (yellow triangle) on the auto-imported
preset kit because CMakePresets cannot specify a debugger path — only
compiler paths.  Qt Creator pairs the MinGW compiler from the preset
with whatever debugger it auto-detects, which often picks an MSVC
`cdb.exe` or a system `gdb` whose ABI doesn't match.

**One-time fix** (per machine, not per project):

1. *Edit → Preferences → Kits → Debuggers* tab → check there's an entry
   for `C:\\Qt\\Tools\\mingw1310_64\\bin\\gdb.exe`.  If not: *Add* →
   *Path* = that path, *Name* = `MinGW gdb (Qt 6.11)`.  *Apply*.
2. *Kits* tab → select the auto-imported kit named after the preset
   (e.g. `vcpkg + Qt MinGW 13.1.0 (Release)`) → set *Debugger* to the
   `MinGW gdb (Qt 6.11)` entry from step 1.  *Apply* + *OK*.

The warning disappears, and breakpoint debugging works against the
generated executables.  The fix sticks across project re-imports
because Qt Creator stores it in the kit, not the preset.

> If the Qt Creator installer registered the bundled gdb under a
> different name (sometimes `MinGW Debugger`), step 1 is unnecessary —
> just pick the existing entry in step 2.

### Skip vcpkg compile (use prebuilt) — step-by-step

Download `vcpkg_installed_x64-mingw-qt.zip` from the SharePoint folder
linked in `README.html` (~50–80 MB).

#### Preset flow (recommended)

1. If a full vcpkg compile is currently running, **Build → Cancel Build**.
2. Use the bundled `vcpkg-x64-mingw-qt-prebuilt` preset (it has
   `VCPKG_MANIFEST_INSTALL=OFF` baked in).  If the project was opened
   with a kit instead: *File → Close Project*, delete
   `CMakeLists.txt.user`, reopen `CMakeLists.txt`, tick the
   `vcpkg-x64-mingw-qt-prebuilt` preset.
3. **Configure Project** → fails at `find_package(gRPC)` (expected — the
   build dir is now created).
4. From a terminal at project root:

   ```cmd
   import_prebuilt.bat C:\\path\\to\\vcpkg_installed_x64-mingw-qt.zip
   ```

5. Back in Qt Creator: *Build → Run CMake* (1–3 sec) → *Build → Build All*.

#### Kit flow (Desktop Qt 6.x MinGW 64-bit)

1. **Build → Cancel Build** if a vcpkg compile is running.
2. **Build → Clear CMake Configuration** (not *Clean* — that leaves
   `CMakeCache.txt`).
3. *Projects (Ctrl+5) → Build → Initial Configuration → Add → Boolean*:

   ```
   VCPKG_MANIFEST_INSTALL = OFF
   ```

   (or *Add → String* with value `OFF` — vcpkg parses both).  Without
   this, vcpkg will overwrite the imported tree.
4. **Run CMake** → fails at `find_package(gRPC)` (expected; build dir is
   created).
5. From a terminal at project root:

   ```cmd
   import_prebuilt.bat C:\\path\\to\\vcpkg_installed_x64-mingw-qt.zip
   ```

   Verify:

   ```cmd
   dir build\\Desktop_Qt_*\\vcpkg_installed\\x64-mingw-qt\\share\\grpc\\
   ```

   should list `gRPCConfig.cmake`.
6. Back in Qt Creator: **Run CMake** (1–3 sec) → **Build All**.

#### Verify it really used the prebuilt

In *General Messages* after configure, you should see:

```
-- The CXX compiler identification is GNU 13.1.0
-- Found gRPC: <build-dir>/vcpkg_installed/x64-mingw-qt/share/grpc
-- Found Protobuf: ...
-- Configuring done (X.Xs)
```

You should **NOT** see lines like:

```
-- Building boringssl[core]:x64-mingw-qt...
-- Building abseil[core]:x64-mingw-qt...
```

If you do, `VCPKG_MANIFEST_INSTALL=OFF` didn't reach the toolchain —
check *Initial Configuration* still has the entry, then *Clear CMake
Configuration* + *Run CMake* again.

### Running the GUI from Qt Creator (F5) — fix `libprotobuf.dll not found`

After a successful build, F5 launches the `.exe` directly from the build
dir.  Windows only searches the `.exe`'s folder and `%PATH%` for DLLs —
neither has the vcpkg deps, Qt, or MinGW runtime.  You'll see one of:

```
The code execution cannot proceed because libprotobuf.dll was not found.
... Qt6Core.dll was not found.
... libgcc_s_seh-1.dll was not found.
```

**Fix once per kit/preset**: *Projects (Ctrl+5) → Run → Environment →
Details*, select `Path`, click *Edit*.  Prepend (semicolon-separated,
replace `<build-dir>` with the build dir shown in the *Build* tab —
e.g. `build/Desktop_Qt_*-Debug` or `build-qt-vcpkg`):

```
<build-dir>\\vcpkg_installed\\x64-mingw-qt\\bin;C:\\Qt\\6.x.y\\mingw_64\\bin;C:\\Qt\\Tools\\mingw1310_64\\bin
```

Repeat on `qt_client_grpcpp/`'s own *Run → Environment* (separate
sub-project, separate build dir).  Survives rebuilds; only redo when the
build dir name changes (Debug↔Release, kit switch).

**Permanent alternative — deploy script**:

```cmd
deploy_qt_vcpkg.bat                       :: server
cd qt_client_grpcpp && deploy_qt.bat      :: client
```

Each copies every DLL next to the `.exe` in `dist-qt-vcpkg/`.  That
folder is fully self-contained and runs without any PATH setup —
ideal when shipping to a teammate or test machine.
'''
    return f'''# {spec.service_name}

Monorepo containing {len(services)} gRPC services that share a single
`.proto` file and build from one CMakeLists.

## Services

{svc_lines}

## Folder structure

`[edit]` marks files you'll write business logic into.  Everything else
is scaffolding regenerated by `mb-scaffold` — safe to leave alone.

```
{spec.service_name}/
├── proto/{spec.snake_name}.proto     # one shared .proto for all services
├── src/<service_snake>/              # one folder per service
│   ├── main.cpp                      # ServiceRunner entry-point
│   ├── domain/<Service>.{{h,cpp}}      # [edit] business logic (pure C++)
│   └── adapters/api/<Service>GrpcAdapter.{{h,cpp}}  # [edit] proto<->domain wrapper
├── deploy/<service_snake>.nomad.hcl  # one Nomad job per service
├── client/                           # console client subproject (one .exe per service)
├── CMakeLists.txt                    # single project, N add_executable() calls
├── build_deploy.bat / .sh            # one-shot build for all services
├── set_env*.bat / .sh                # toolchain env (VCPKG_ROOT, QT_DIR, ...)
└── dist/                             # output: N .exe's + shared DLLs
```

## Build & run flow

```mermaid
flowchart TD
    Start([Start])
    Setup["1\\. One-time setup<br/>setx VCPKG_ROOT, QT_DIR, QT_MINGW_BIN"]
    Choose{{"Toolchain?"}}
    Prebuilt{{"Have prebuilt zip?"}}
    Import["import_prebuilt.bat &lt;zip&gt;<br/>~30 seconds"]
    BuildVcpkg["build_qt_vcpkg.bat<br/>(or Qt Creator F5)"]
    BuildMSYS2["build_deploy_msys2.bat"]
    BuildResult["build*/<service>.exe<br/>(N executables) + DLLs"]
    LocalRun["Run any service:<br/>./<service>.exe"]
    Pkg["deploy_qt_vcpkg.bat<br/>→ dist-qt-vcpkg/"]
    NomadRun["nomad job run<br/>deploy/&lt;svc&gt;.nomad.hcl<br/>(per-service jobs)"]
    Discover["Clients discover via Consul<br/>(one entry per service)"]

    Start --> Setup --> Choose
    Choose -->|"Qt MinGW + vcpkg<br/>(recommended)"| Prebuilt
    Choose -->|MSYS2| BuildMSYS2 --> BuildResult
    Prebuilt -->|"Yes (~2 min total)"| Import --> BuildVcpkg
    Prebuilt -->|"No (first build ~30-60 min)"| BuildVcpkg
    BuildVcpkg --> BuildResult
    BuildResult --> LocalRun
    BuildResult -->|For sharing| Pkg
    LocalRun --> NomadRun
    Pkg --> NomadRun
    NomadRun --> Discover
```

## Prerequisites

This service depends on the **MicroserviceBase** runtime (C++ library +
CMake package).  `CMakeLists.txt` calls
`find_package(MicroserviceBase CONFIG)` first, then falls back to
`add_subdirectory(.../MicroserviceBase/runtime_cpp)` for in-tree builds.

Pick one of three setups (any of them satisfies the dependency):

| Setup | When to use | One-time steps |
|---|---|---|
| **A. In-tree (zero install)** | You're working inside the framework checkout | Clone framework so this scaffold sits at `<framework>/examples/<svc>/` — the relative path `../../MicroserviceBase/runtime_cpp` resolves automatically |
| **A2. `MICROSERVICEBASE_DIR` env var** | Scaffold lives anywhere outside `examples/` | `setx MICROSERVICEBASE_DIR D:\workspace\python-microservice-base` (the framework root, the runtime_cpp parent, or runtime_cpp itself — all three are accepted).  Qt Creator inherits user env, so it picks this up too. |
| **B. CMake install** | Standalone service, no vcpkg | `cmake -S <framework>/MicroserviceBase/runtime_cpp -B build/mb && cmake --build build/mb && cmake --install build/mb --prefix $HOME/.local/microservice-base`, then `-DCMAKE_PREFIX_PATH=$HOME/.local/microservice-base` on configure |
| **C. vcpkg overlay-port** | Already using vcpkg (the Qt+vcpkg path below) | Add `microservice-base` to your `vcpkg.json` `dependencies` and pass `-DVCPKG_OVERLAY_PORTS=<framework>/ports` |

**Get the framework** (branch `ugc1hc/feat/migrate_to_ta_architecture` is
the current TA-architecture line — the gRPC + Consul + Nomad runtime
this scaffold targets):

```cmd
git clone -b ugc1hc/feat/migrate_to_ta_architecture ^
    https://github.com/test-fullautomation/python-microservice-base.git
:: → MicroserviceBase/runtime_cpp/  (C++ runtime, used by all three setups above)
:: → ports/microservice-base/       (vcpkg overlay-port for setup C)
:: → docs/runtime_cpp_install.md    (full instructions for each setup)
```

If `cmake -S .` fails with `MicroserviceBase runtime not found.  Install
+ add to CMAKE_PREFIX_PATH`, that's this dependency missing — pick a
setup above.

## Build

```cmd
build_deploy.bat        :: Windows (MSVC)
./build_deploy.sh       # Linux
```

Each service is an independent executable listening on its own gRPC port
(see the `*_GRPC_PORT` env var per service).  All services register with
the same Consul agent by default.{full_kit_walkthrough_md}{qtc_section}
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
    # The Google-grpc GUI (client/gui/) only emits when client_grpc_kind ==
    # "google".  For "qt" or "google_vcpkg", the user's primary GUI lives in
    # qt_client/ or qt_client_grpcpp/ - emitting client/gui/ would just be
    # duplicated work with no upside.
    ui_kind = spec.gui_type if (spec.gui_type in ("widget", "wasm", "qml")
                                and spec.client_grpc_kind == "google") else "none"
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
    "${{STUB_INC}}")

target_link_libraries({project_snake}_gui PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
    Qt6::Widgets)

set_target_properties({project_snake}_gui PROPERTIES
    WIN32_EXECUTABLE ON
    MACOSX_BUNDLE    ON)

mb_deploy_runtime({project_snake}_gui QT_APP)
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
    "${{STUB_INC}}")

target_link_libraries({project_snake}_gui PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
    Qt6::Quick
    Qt6::Qml)

mb_deploy_runtime({project_snake}_gui QT_APP)
'''

    return f'''cmake_minimum_required(VERSION 3.16)

# vcpkg auto-detection BEFORE project() (paths climb one level: ../triplets, ../ports).
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "{spec.service_name}Client: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing.")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (auto-set from ../triplets overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets"
            CACHE PATH "vcpkg overlay triplets directory")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports"
            CACHE PATH "vcpkg overlay ports directory")
    endif()
endif()
if(NOT DEFINED QT_CREATOR_SKIP_VCPKG_SETUP)
    set(QT_CREATOR_SKIP_VCPKG_SETUP ON CACHE BOOL "")
endif()
if(NOT CMAKE_MAKE_PROGRAM)
    set(_ninja_candidates "C:/Qt/Tools/Ninja/ninja.exe" "C:/Qt/Tools/Ninja_64/ninja.exe")
    if(DEFINED ENV{{VCPKG_ROOT}})
        file(GLOB _vcpkg_ninja "$ENV{{VCPKG_ROOT}}/downloads/tools/ninja-*/ninja.exe")
        list(APPEND _ninja_candidates ${{_vcpkg_ninja}})
    endif()
    foreach(_n IN LISTS _ninja_candidates)
        if(EXISTS "${{_n}}")
            set(CMAKE_MAKE_PROGRAM "${{_n}}" CACHE FILEPATH "Ninja (auto-detected)")
            break()
        endif()
    endforeach()
endif()

project({spec.service_name}Client VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Manifest-mode fallback: use prebuilt vcpkg_installed/x64-mingw-qt/ if present.
if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc (target triplet)")
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)

# MicroserviceBase runtime — resolution order:
#   1. find_package() — installed package or vcpkg overlay
#   2. MICROSERVICEBASE_DIR env var (set once, works from any location)
#   3. ../../../MicroserviceBase/runtime_cpp — in-tree fallback for
#      <framework>/examples/<svc>/qt_client_grpcpp/.
find_package(MicroserviceBase CONFIG QUIET)
if(NOT MicroserviceBase_FOUND)
    set(_mb_candidates "")
    if(DEFINED ENV{{MICROSERVICEBASE_DIR}})
        list(APPEND _mb_candidates
            "$ENV{{MICROSERVICEBASE_DIR}}/MicroserviceBase/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}")
    endif()
    list(APPEND _mb_candidates
        "${{CMAKE_CURRENT_SOURCE_DIR}}/../../../MicroserviceBase/runtime_cpp")
    set(_mb_in_tree "")
    foreach(_p IN LISTS _mb_candidates)
        if(EXISTS "${{_p}}/CMakeLists.txt")
            set(_mb_in_tree "${{_p}}")
            break()
        endif()
    endforeach()
    if(_mb_in_tree)
        add_subdirectory("${{_mb_in_tree}}"
                         "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")
    else()
        message(FATAL_ERROR
            "MicroserviceBase runtime not found.  Set MICROSERVICEBASE_DIR env "
            "var to your framework checkout, or install + add to CMAKE_PREFIX_PATH "
            "(see docs/runtime_cpp_install.md).")
    endif()
endif()

# Shared proto stubs from the parent project's proto/ folder.
# Auto-generate at build time if pre-generated stubs are missing.
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/../proto")
if(EXISTS "${{PROTO_DIR}}/{sn}.pb.h")
    set(STUB_SRCS
        "${{PROTO_DIR}}/{sn}.pb.cc"
        "${{PROTO_DIR}}/{sn}.grpc.pb.cc")
    set(STUB_INC "${{PROTO_DIR}}")
else()
    set(GEN_DIR "${{CMAKE_CURRENT_BINARY_DIR}}/gen")
    file(MAKE_DIRECTORY "${{GEN_DIR}}")
    set(STUB_SRCS
        "${{GEN_DIR}}/{sn}.pb.cc"
        "${{GEN_DIR}}/{sn}.grpc.pb.cc")
    set(STUB_INC "${{GEN_DIR}}")
    if(TARGET protobuf::protoc)
        get_target_property(_protoc protobuf::protoc LOCATION)
    else()
        find_program(_protoc NAMES protoc protoc.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/protobuf"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf"
            REQUIRED)
    endif()
    if(TARGET gRPC::grpc_cpp_plugin)
        get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin LOCATION)
    else()
        find_program(_grpc_cpp NAMES grpc_cpp_plugin grpc_cpp_plugin.exe
            HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/grpc"
                  "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/grpc"
            REQUIRED)
    endif()
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
        COMMENT "Auto-generating gRPC stubs into ${{GEN_DIR}}")
endif()

{_MB_DEPLOY_RUNTIME_BLOCK}
# ---- Console client ----------------------------------------------------
add_executable({project_snake}_client
    src/client.cpp
{console_sources}
    ${{STUB_SRCS}})

target_include_directories({project_snake}_client PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{STUB_INC}}")

target_link_libraries({project_snake}_client PRIVATE
    microservice_base::runtime
    gRPC::grpc++ protobuf::libprotobuf)
mb_deploy_runtime({project_snake}_client)
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

/// Set the Consul HTTP API URL used by every subsequent invoke() in
/// Consul-discovery mode.  Pass an empty string to fall back to the
/// CONSUL_ADDR env var, or http://127.0.0.1:8500 if env unset.
/// Changing it resets all cached clients.
void set_consul_addr(const std::string& consulAddr);

/// Probe the Consul HTTP API at consulAddr (GET /v1/agent/self) with a
/// 3-second timeout.  Returns {ok, message} for the GUI's Connect button.
std::pair<bool, std::string> ping_consul(const std::string& consulAddr);

/// Open a gRPC channel to hostPort and block up to 3 seconds for the
/// HTTP/2 handshake.  Used by the GUI's Connect button in direct mode.
std::pair<bool, std::string> ping_direct(const std::string& hostPort);

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
                        "{svc_snake}", g_consul_addr);
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
std::string g_consul_addr;   // empty = use ServiceClient default (env or 127.0.0.1:8500)

{chr(10).join(client_slots)}

{chr(10).join(getter_fns)}

}}  // anonymous

void set_direct_host(const std::string& hostPort) {{
    if (hostPort == g_direct_host) return;
    g_direct_host = hostPort;
{reset_stmts}
}}

void set_consul_addr(const std::string& consulAddr) {{
    if (consulAddr == g_consul_addr) return;
    g_consul_addr = consulAddr;
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

// ---------------------------------------------------------------------------
// Connectivity probes used by the GUI's Connect button.
// libcurl is already linked via MicroserviceBase runtime (Consul HTTP).
// ---------------------------------------------------------------------------
#include <curl/curl.h>
#include <chrono>

namespace client_registry {{
namespace {{
size_t _curl_sink(char*, size_t size, size_t nmemb, void*) {{ return size * nmemb; }}
}}

std::pair<bool, std::string> ping_consul(const std::string& consulAddr) {{
    if (consulAddr.empty()) return {{ false, "Consul URL is empty" }};
    const std::string url = consulAddr + "/v1/agent/self";

    CURL* h = curl_easy_init();
    if (!h) return {{ false, "curl_easy_init failed" }};
    char errbuf[CURL_ERROR_SIZE] = {{0}};
    curl_easy_setopt(h, CURLOPT_URL, url.c_str());
    curl_easy_setopt(h, CURLOPT_WRITEFUNCTION, _curl_sink);
    curl_easy_setopt(h, CURLOPT_TIMEOUT, 3L);
    curl_easy_setopt(h, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(h, CURLOPT_ERRORBUFFER, errbuf);
    CURLcode rc = curl_easy_perform(h);
    long http_code = 0;
    curl_easy_getinfo(h, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(h);

    if (rc != CURLE_OK)
        return {{ false, std::string("Consul unreachable: ") + (errbuf[0] ? errbuf : curl_easy_strerror(rc)) }};
    if (http_code != 200)
        return {{ false, "Consul returned HTTP " + std::to_string(http_code) }};
    return {{ true, "Consul reachable: " + consulAddr }};
}}

std::pair<bool, std::string> ping_direct(const std::string& hostPort) {{
    if (hostPort.empty()) return {{ false, "Host:port is empty" }};
    auto channel = grpc::CreateChannel(hostPort, grpc::InsecureChannelCredentials());
    if (!channel) return {{ false, "grpc::CreateChannel returned null" }};
    auto deadline = std::chrono::system_clock::now() + std::chrono::seconds(3);
    if (channel->WaitForConnected(deadline))
        return {{ true, "Connected to " + hostPort }};
    return {{ false, "Cannot reach " + hostPort + " within 3s" }};
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
    void onConnect();
    void onConsulToggled(bool consul);

private:
    void applyHostMode();

    QLineEdit*   m_directHost = nullptr;
    QLineEdit*   m_consulAddr = nullptr;
    QCheckBox*   m_useConsul  = nullptr;
    QComboBox*   m_serviceCombo = nullptr;
    QComboBox*   m_methodCombo  = nullptr;
    QTextEdit*   m_requestEdit  = nullptr;
    QTextEdit*   m_responseEdit = nullptr;
    QPushButton* m_connectButton = nullptr;
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
#include <QApplication>
#include <QVBoxLayout>
#include <cstdlib>

MainWindow::MainWindow(QWidget* parent) : QWidget(parent) {{
    setWindowTitle("{title}");
    resize(820, 640);

    auto* v = new QVBoxLayout(this);

    // ---- Consul address row ----
    auto* consulRow = new QHBoxLayout;
    consulRow->addWidget(new QLabel("Consul:", this));
    m_consulAddr = new QLineEdit(this);
    m_consulAddr->setPlaceholderText("http://127.0.0.1:8500");
    {{
        const char* env = std::getenv("CONSUL_ADDR");
        m_consulAddr->setText(env && *env ? QString::fromUtf8(env)
                                          : "http://127.0.0.1:8500");
    }}
    consulRow->addWidget(m_consulAddr, 1);
    v->addLayout(consulRow);

    // ---- Host row (Consul on/off + direct host:port override) ----
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

    // ---- Connect + Send + status ----
    auto* sendRow = new QHBoxLayout;
    m_connectButton = new QPushButton("Connect", this);
    m_sendButton = new QPushButton("Send", this);
    m_statusLabel = new QLabel("(not connected)", this);
    sendRow->addWidget(m_connectButton);
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
            [this]() {{
                m_statusLabel->setText("(not connected)");
                applyHostMode();
            }});
    connect(m_consulAddr, &QLineEdit::editingFinished, this,
            [this]() {{
                m_statusLabel->setText("(not connected)");
                client_registry::set_consul_addr(m_consulAddr->text().toStdString());
                applyHostMode();
            }});
    connect(m_connectButton, &QPushButton::clicked, this, &MainWindow::onConnect);

    // Push initial consul addr down so the first invoke uses it.
    client_registry::set_consul_addr(m_consulAddr->text().toStdString());
    applyHostMode();
}}

void MainWindow::onConsulToggled(bool consul) {{
    m_directHost->setEnabled(!consul);
    applyHostMode();
}}

void MainWindow::onConnect() {{
    m_connectButton->setEnabled(false);
    m_statusLabel->setText("Connecting...");
    QApplication::processEvents();   // flush UI before the blocking probe

    std::pair<bool, std::string> result;
    if (m_useConsul->isChecked()) {{
        const auto addr = m_consulAddr->text().trimmed().toStdString();
        client_registry::set_consul_addr(addr);
        result = client_registry::ping_consul(addr);
    }} else {{
        const auto host = m_directHost->text().trimmed().toStdString();
        applyHostMode();
        result = client_registry::ping_direct(host);
    }}
    m_statusLabel->setText(QString::fromStdString(
        std::string(result.first ? "OK: " : "FAIL: ") + result.second));
    m_connectButton->setEnabled(true);
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


# =======================================================================
# Multi-proto mode — N gRPC services hosted in ONE binary.
# =======================================================================
#
# Vehicle-example pattern: one project, N .proto files (each declaring
# its own service + messages), one main.cpp that calls
# ServiceRunner::addService() N times so all services register on the
# same grpc::ServerBuilder and share one Consul registration / one port.
#
# Layout:
#   <project>/
#   ├── proto/<svc1_snake>.proto       (or whatever .proto file user named)
#   ├── proto/<svc2_snake>.proto
#   ├── src/main.cpp                   (registers ALL services)
#   ├── src/Settings.h                 (shared)
#   ├── src/<svc1_snake>/
#   │   ├── domain/<Svc1>.{h,cpp}
#   │   └── adapters/api/<Svc1>GrpcAdapter.{h,cpp}
#   ├── src/<svc2_snake>/
#   │   └── ... same pattern ...
#   ├── deploy/<project_snake>.nomad.hcl   (one job, one .exe)
#   ├── CMakeLists.txt                  (N codegens, 1 add_executable)
#   └── README.md
#
# Each service has its OWN proto package (defaults to <svc_snake>.v1)
# so message names from different services don't collide.

def _mp_proto_filename(svc) -> str:
    """Service's .proto filename inside proto/ — respects ServiceBlock.proto_file
    when set, otherwise derives <svc_snake>.proto from the service name."""
    return svc.proto_file or f"{_mono_snake(svc.name)}.proto"


def _mp_proto_package(svc) -> str:
    """Per-service proto package.

    When the service carries verbatim .proto content (imported by the
    user), parse the `package X;` declaration from it -- the generated
    C++ stubs use that exact package as the namespace, so we MUST match
    it in the adapter code or every type reference fails.

    Fallback when proto_content is empty (auto-generated proto): use
    `<snake>.v1` to keep versioning consistent with single-service mode.
    """
    if getattr(svc, "proto_content", None):
        m = re.search(r"^\s*package\s+([\w.]+)\s*;",
                      svc.proto_content, re.MULTILINE)
        if m:
            return m.group(1)
    return f"{_mono_snake(svc.name)}.v1"


def _mp_proto_namespace(svc) -> str:
    return _mp_proto_package(svc).replace(".", "::")


def _mp_proto_basename(svc) -> str:
    """Strip .proto so we can compose <basename>.pb.h / .grpc.pb.h."""
    fn = _mp_proto_filename(svc)
    return fn[:-6] if fn.endswith(".proto") else fn


def generate_multi_proto(spec: "ScaffoldSpec", services) -> Dict[str, str]:
    """Emit a multi-proto / single-binary scaffold (vehicle-example pattern).

    Each service in ``services`` becomes:
      * its own ``.proto`` file under ``proto/`` (with its own package),
      * its own ``domain/`` + ``adapters/api/`` source folder,
    and ALL services are registered on one grpc::ServerBuilder by the
    project's single ``src/main.cpp``.

    v1: C++ only.  Borrows monorepo CMake auto-detection +
    set_env / build script infrastructure unchanged.
    """
    files: Dict[str, str] = {}

    # ---- N proto files (one per service) ----
    for svc in services:
        proto_path = f"proto/{_mp_proto_filename(svc)}"
        if svc.proto_content:
            files[proto_path] = svc.proto_content
        else:
            files[proto_path] = _mp_gen_proto(svc)

    # Stub-generation helper: same script as monorepo, but it walks all
    # .proto files in proto/ rather than a single one.
    files["proto/generate_stubs.bat"] = _mp_gen_stubs_bat(spec, services)
    files["proto/generate_stubs.sh"] = _mp_gen_stubs_sh(spec, services)

    # ---- Shared env scripts (reused from monorepo / single-service) ----
    files["set_env.bat"] = _set_env_bat(spec)
    files["set_env.sh"] = _set_env_sh(spec)
    files["set_env_mingw.bat"] = _set_env_mingw_bat(spec)
    files["set_env_msys2.bat"] = _set_env_msys2_bat(spec)

    # ---- Root CMakeLists ----
    files["CMakeLists.txt"] = _mp_cmake(spec, services)

    # ---- One main.cpp + one Settings.h at src/ root ----
    files["src/main.cpp"] = _mp_main_cpp(spec, services)
    files["src/Settings.h"] = _mp_settings_h(spec)

    # ---- Per-service domain + adapter ----
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        svc_pascal = svc.name
        files[f"src/{svc_snake}/domain/{svc_pascal}.h"]   = _mp_domain_h(spec, svc)
        files[f"src/{svc_snake}/domain/{svc_pascal}.cpp"] = _mp_domain_cpp(spec, svc)
        files[f"src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.h"]   = _mp_adapter_h(spec, svc)
        files[f"src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.cpp"] = _mp_adapter_cpp(spec, svc)

    # ---- Single Nomad job ----
    if spec.gen_nomad:
        files[f"deploy/{spec.snake_name}.nomad.hcl"] = _mp_nomad(spec, services)

    # ---- Console client subproject ----
    # Standalone CMake project under client/ that connects to the multi-
    # service binary's Consul registration (one host:port for all services)
    # and exposes a service -> method picker.  Each per-service proto stub
    # uses its own namespace; the client links them all.
    files.update(_mp_client_files(spec, services))

    # ---- Optional Qt-native client in qt_client_grpcpp/ (Google grpc++ via vcpkg) ----
    # Same trigger as the single-service path: requires gui_type != "none"
    # AND client_grpc_kind == "google_vcpkg".  Adapted for multi_proto:
    # writes each service's .proto verbatim, emits N protoc codegens, links
    # the union of stubs into one Qt Widgets exe.
    client_uses_vcpkg = (spec.gui_type != "none"
                        and spec.client_grpc_kind == "google_vcpkg")
    if client_uses_vcpkg:
        files.update(_mp_qt_client_grpcpp_files(spec, services))

    # ---- Server vcpkg path (Google grpc++ via vcpkg + Qt MinGW) ----
    server_uses_vcpkg = spec.server_grpc_kind == "vcpkg"
    if server_uses_vcpkg:
        files["vcpkg.json"] = _server_vcpkg_json(spec)
        if spec.gen_build_scripts:
            files["build_qt_vcpkg.bat"]  = _server_build_qt_vcpkg_bat(spec)
            files["deploy_qt_vcpkg.bat"] = _server_deploy_qt_vcpkg_bat(spec)

    # ---- Shared vcpkg infrastructure (triplets/ + ports/ + init script) ----
    # Emit once if EITHER side uses vcpkg.  Both sides share triplet,
    # overlay-port, binary cache.
    if client_uses_vcpkg or server_uses_vcpkg:
        files.update(_vcpkg_shared_files(spec))

    # ---- Build scripts (reuse monorepo's — they call cmake against the
    # single CMakeLists, which doesn't care how many services it builds) ----
    if spec.gen_build_scripts:
        files["build_deploy.bat"] = _mp_build_bat(spec)
        files["build_deploy.sh"] = _mp_build_sh(spec)

    # ---- README ----
    # Markdown is multi_proto-specific; HTML reuses the monorepo emitter
    # for now (it covers the same Qt Creator + vcpkg flow, with mostly
    # identical troubleshooting and quick-reference content; "monorepo"
    # wording in a few places vs. "multi_proto" is the only mismatch).
    # A dedicated _mp_readme_html() can come later if needed.
    if spec.gen_readme:
        files["README.md"]   = _mp_readme(spec, services)
        files["README.html"] = _mono_readme_html(spec, services)

    return files


# ---- Console client for multi_proto ---------------------------------
def _mp_client_files(spec, services) -> Dict[str, str]:
    """Standalone client subproject under client/.

    One CMake project, one .exe, links in every service's stubs from the
    parent project's proto/ folder and connects to the parent's Consul
    registration (single host:port).  Discovery uses the project's
    snake_name as the Consul service name.

    Stays minimal: console-only menu, no UI variants (the monorepo client
    family has those if a user wants to upgrade later).
    """
    sn = spec.snake_name
    project_name = spec.service_name
    files = {}

    files["client/CMakeLists.txt"]  = _mp_client_cmake(spec, services)
    files["client/src/client.cpp"]  = _mp_client_main_cpp(spec, services)
    files["client/README.md"]       = _mp_client_readme(spec, services)
    return files


def _mp_client_cmake(spec, services) -> str:
    sn = spec.snake_name
    project_name = spec.service_name

    # Each service's .proto is in ../proto/<file>.proto.  We invoke protoc
    # at configure time to generate stubs into the build dir, then list
    # them as sources to add_executable.
    proto_blocks = []
    src_lists = []
    seen = set()
    for svc in services:
        basename = _mp_proto_basename(svc)
        if basename in seen:
            continue
        seen.add(basename)
        var = basename.upper() + "_SRCS"
        proto_filename = _mp_proto_filename(svc)
        src_lists.append(f"${{{var}}}")
        # VERBATIM-quoting note: see _mp_proto_codegen_block — drop the
        # inner quotes so protoc doesn't get them as part of the path.
        proto_blocks.append(f'''add_custom_command(
    OUTPUT
        "${{GEN_DIR}}/{basename}.pb.cc"  "${{GEN_DIR}}/{basename}.pb.h"
        "${{GEN_DIR}}/{basename}.grpc.pb.cc" "${{GEN_DIR}}/{basename}.grpc.pb.h"
    COMMAND ${{_protoc}}
        --proto_path=${{PROTO_DIR}}
        --cpp_out=${{GEN_DIR}}
        --grpc_out=${{GEN_DIR}}
        --plugin=protoc-gen-grpc=${{_grpc_cpp}}
        ${{PROTO_DIR}}/{proto_filename}
    DEPENDS "${{PROTO_DIR}}/{proto_filename}"
    COMMENT "Generating gRPC stubs for {proto_filename} (client)"
    VERBATIM)
set({var}
    "${{GEN_DIR}}/{basename}.pb.cc"
    "${{GEN_DIR}}/{basename}.grpc.pb.cc")''')

    proto_codegen = '\n'.join(proto_blocks)
    src_var_uses = '\n    '.join(src_lists)

    return f'''cmake_minimum_required(VERSION 3.16)

# vcpkg auto-detection BEFORE project() so the toolchain loads correctly.
# Mirrors the parent CMakeLists; overlays come from the parent project
# (../triplets, ../ports).
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected)")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (parent overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets"
            CACHE PATH "vcpkg overlay triplets")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports"
            CACHE PATH "vcpkg overlay ports")
    endif()
endif()

project({project_name}Client VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Manifest-mode fallback for prebuilt vcpkg_installed/.
if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE
   AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE
        "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc")
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(CURL     CONFIG REQUIRED)

# MicroserviceBase runtime — provides ServiceClient<T>.  Find via
# installed package, env var, or in-tree fallback.
find_package(MicroserviceBase CONFIG QUIET)
if(NOT MicroserviceBase_FOUND)
    set(_mb_candidates "")
    if(DEFINED ENV{{MICROSERVICEBASE_DIR}})
        list(APPEND _mb_candidates
            "$ENV{{MICROSERVICEBASE_DIR}}/MicroserviceBase/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}")
    endif()
    list(APPEND _mb_candidates
        "${{CMAKE_CURRENT_SOURCE_DIR}}/../../../MicroserviceBase/runtime_cpp")
    set(_mb_in_tree "")
    foreach(_p IN LISTS _mb_candidates)
        if(EXISTS "${{_p}}/CMakeLists.txt")
            set(_mb_in_tree "${{_p}}")
            break()
        endif()
    endforeach()
    if(_mb_in_tree)
        add_subdirectory("${{_mb_in_tree}}"
                         "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")
    else()
        message(FATAL_ERROR
            "MicroserviceBase runtime not found.  Set MICROSERVICEBASE_DIR or "
            "install + add to CMAKE_PREFIX_PATH (see docs/runtime_cpp_install.md).")
    endif()
endif()

{_MB_DEPLOY_RUNTIME_BLOCK}

# ---- Proto stubs (shared with the parent server, regenerated here) ---
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/../proto")
set(GEN_DIR "${{CMAKE_CURRENT_BINARY_DIR}}/gen")
file(MAKE_DIRECTORY "${{GEN_DIR}}")
if(TARGET protobuf::protoc)
    get_target_property(_protoc protobuf::protoc LOCATION)
else()
    find_program(_protoc NAMES protoc protoc.exe
        HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/protobuf"
              "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf"
        REQUIRED)
endif()
if(TARGET gRPC::grpc_cpp_plugin)
    get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin LOCATION)
else()
    find_program(_grpc_cpp NAMES grpc_cpp_plugin grpc_cpp_plugin.exe
        HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/grpc"
              "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/grpc"
        REQUIRED)
endif()

{proto_codegen}

# ---- Console client executable ---------------------------------------
add_executable({sn}_client
    src/client.cpp
    {src_var_uses}
)

target_include_directories({sn}_client PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{GEN_DIR}}"
)

target_link_libraries({sn}_client PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
)
mb_deploy_runtime({sn}_client)
'''


def _mp_client_main_cpp(spec, services) -> str:
    """Console client.

    Connects via Consul (looks up the parent project's service name) OR
    --direct host:port; instantiates every service's stub on the same
    channel; offers an interactive service -> method picker.

    Method-level invocation is a stub for v1 — the user fills in
    request fields per their proto.  The framework hands back a working
    channel + stub for each service so they don't write the connection
    plumbing.
    """
    sn = spec.snake_name
    project_name = spec.service_name

    includes = []
    stubs = []
    list_lines = []
    for svc in services:
        basename = _mp_proto_basename(svc)
        ns = _mp_proto_namespace(svc)
        svc_pascal = svc.name
        if f'#include "{basename}.grpc.pb.h"' not in includes:
            includes.append(f'#include "{basename}.grpc.pb.h"')
        stubs.append(
            f'        auto {_mono_snake(svc.name)}_stub = '
            f'::{ns}::{svc_pascal}::NewStub(channel);'
        )
        method_names = ", ".join(m.name for m in svc.methods) if svc.methods else "(no methods)"
        list_lines.append(
            f'        std::cout << "  {svc_pascal}: {method_names}" << std::endl;'
        )

    inc_block = '\n'.join(includes)
    stub_block = '\n'.join(stubs)
    list_block = '\n'.join(list_lines)

    return f'''// Console client for {project_name} (multi-proto).
//
// All services are hosted by ONE binary on ONE port, so we make ONE
// channel and instantiate all per-service stubs on it.
//
// Usage:
//   {sn}_client                    # discover host:port via Consul (default)
//   {sn}_client --direct HOST:PORT # bypass Consul, connect directly

#include <iostream>
#include <memory>
#include <string>

#include <grpcpp/grpcpp.h>
#include "MicroserviceBase/ServiceClient.h"

{inc_block}

int main(int argc, char** argv) {{
    std::string target;
    bool direct = false;
    for (int i = 1; i < argc; ++i) {{
        std::string a(argv[i]);
        if (a == "--direct" && i + 1 < argc) {{
            target = argv[++i];
            direct = true;
        }}
    }}

    if (!direct) {{
        // Discover the multi-service binary via Consul.  All hosted services
        // share ONE registration named after the project's snake_name, so
        // one lookup yields the host:port for every service.
        const char* consul_addr_env = std::getenv("{sn.upper()}_CONSUL_ADDR");
        std::string consul_addr = consul_addr_env
            ? consul_addr_env : "http://127.0.0.1:8500";
        microservice_base::ConsulResolver resolver(consul_addr);
        auto endpoint = resolver.resolve("{sn}");
        if (endpoint.empty()) {{
            std::cerr << "Consul lookup for '{sn}' returned no instances. "
                      << "Pass --direct HOST:PORT to bypass." << std::endl;
            return 1;
        }}
        target = endpoint;
    }}

    std::cout << "Connecting to {project_name} @ " << target << std::endl;
    auto channel = grpc::CreateChannel(target, grpc::InsecureChannelCredentials());

    try {{
{stub_block}

        std::cout << "\\nHosted services + methods:" << std::endl;
{list_block}
        std::cout << std::endl;
        std::cout << "TODO: replace this scaffold with your own RPC calls." << std::endl;
        std::cout << "Each *_stub above is ready to use, e.g.:" << std::endl;
        std::cout << "  grpc::ClientContext ctx;" << std::endl;
        std::cout << "  ::ns::FooRequest req;  ::ns::FooResponse resp;" << std::endl;
        std::cout << "  auto status = your_stub->FooMethod(&ctx, req, &resp);" << std::endl;
    }} catch (const std::exception& e) {{
        std::cerr << "Client error: " << e.what() << std::endl;
        return 1;
    }}
    return 0;
}}
'''


def _mp_client_readme(spec, services) -> str:
    sn = spec.snake_name
    svc_lines = "\n".join(
        f"- **{svc.name}** (proto package `{_mp_proto_package(svc)}`)"
        for svc in services
    )
    return f'''# {spec.service_name} — Console client

Connects to the multi-proto server (one Consul registration for the
whole project, one port for all services).

## Hosted services

{svc_lines}

## Build

The client is its own CMake project under `client/`.  Build it
independently of the server:

```cmd
cd client
mkdir build && cd build
cmake -G Ninja ..
cmake --build . --config Release
```

The generated `{sn}_client.exe` discovers the server via Consul
(default `http://127.0.0.1:8500`, override with `{sn.upper()}_CONSUL_ADDR`)
or skip Consul with `--direct HOST:PORT`.

## What the scaffold gives you

For each hosted service it instantiates a ready-to-use gRPC stub:

```cpp
auto svc_a_stub = ::pkg_a::v1::ServiceA::NewStub(channel);
auto svc_b_stub = ::pkg_b::v1::ServiceB::NewStub(channel);
// ... call methods on whichever stub you need
```

The stubs share ONE channel because all services live in one binary
on one port — you don't need separate Consul lookups per service.

## Customising

Edit `src/client.cpp` to build request messages for your real RPC
methods; the comment block at the bottom of `main()` shows the shape.
'''


# ---- Qt Widgets client for multi_proto (qt_client_grpcpp/) ----------
# Triggered when spec.gui_type != "none" AND
# spec.client_grpc_kind == "google_vcpkg".  Mirrors the single-service
# qt_client_grpcpp emitter but writes per-service .proto files and a
# multi-codegen CMakeLists.

def _mp_qt_client_grpcpp_files(spec, services) -> Dict[str, str]:
    files: Dict[str, str] = {}

    # Per-service .proto files (verbatim user-imported text, or generated
    # from spec methods as a fallback).  Dedup by filename so single-file
    # multi-service multi_proto (all share one .proto) writes once.
    seen_proto = set()
    for svc in services:
        proto_filename = _mp_proto_filename(svc)
        if proto_filename in seen_proto:
            continue
        seen_proto.add(proto_filename)
        path = f"qt_client_grpcpp/proto/{proto_filename}"
        files[path] = svc.proto_content or _mp_gen_proto(svc)

    # CMakeLists is multi_proto-aware (PROTOS list expands to N files).
    files["qt_client_grpcpp/CMakeLists.txt"]    = _mp_qt_client_grpcpp_cmake(spec, services)
    files["qt_client_grpcpp/CMakePresets.json"] = _qt_client_grpcpp_cmake_presets()
    files["qt_client_grpcpp/vcpkg.json"]        = _qt_client_grpcpp_vcpkg_json(spec)

    # Reuse single-service Qt UI / build / deploy machinery — these are
    # mostly proto-agnostic.  MainWindow is a placeholder UI; user fills
    # in the per-service buttons / forms after generation.
    files["qt_client_grpcpp/src/main.cpp"]        = _qt_client_grpcpp_main_cpp(spec)
    files["qt_client_grpcpp/src/MainWindow.h"]    = _qt_client_grpcpp_mainwindow_h(spec, services)
    files["qt_client_grpcpp/src/MainWindow.cpp"]  = _qt_client_grpcpp_mainwindow_cpp(spec, services)
    files["qt_client_grpcpp/src/MainWindow.ui"]   = _qt_client_mainwindow_ui(spec)
    files["qt_client_grpcpp/build_qt.bat"]        = _qt_client_grpcpp_build_qt_bat(spec)
    files["qt_client_grpcpp/deploy_qt.bat"]       = _qt_client_grpcpp_deploy_qt_bat(spec)
    files["qt_client_grpcpp/export_prebuilt.bat"] = _qt_client_grpcpp_export_prebuilt_bat(spec)
    files["qt_client_grpcpp/README.md"]           = _qt_client_grpcpp_readme(spec)
    files["qt_client_grpcpp/.gitignore"]          = "build/\nprebuilt/\ndeploy/\n*.user\n"
    return files


def _mp_qt_client_grpcpp_cmake(spec, services) -> str:
    """qt_client_grpcpp/CMakeLists.txt for multi_proto layout.

    Identical to the single-service version EXCEPT the ``_proto_files``
    list expands to every distinct .proto file (deduped by filename, so
    single-file multi-service shares one entry).  protobuf_generate +
    grpc codegen handle CMake lists natively.
    """
    sn = spec.snake_name

    # Build the deduped proto-files list.
    seen = set()
    proto_lines = []
    for svc in services:
        fn = _mp_proto_filename(svc)
        if fn in seen:
            continue
        seen.add(fn)
        proto_lines.append(f'    "${{_proto_path}}/{fn}"')
    proto_files_block = '\n'.join(proto_lines) if proto_lines else '    # no .proto files'

    return f'''cmake_minimum_required(VERSION 3.20)

# vcpkg auto-detection BEFORE project() so the toolchain loads correctly.
# Mirrors the parent server CMakeLists; overlays live in the PARENT project.
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "qt_client_grpcpp: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (parent overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets"
            CACHE PATH "vcpkg overlay triplets")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports"
            CACHE PATH "vcpkg overlay ports")
    endif()
endif()
if(NOT DEFINED QT_CREATOR_SKIP_VCPKG_SETUP)
    set(QT_CREATOR_SKIP_VCPKG_SETUP ON CACHE BOOL "")
endif()
if(NOT CMAKE_MAKE_PROGRAM)
    set(_ninja_candidates "C:/Qt/Tools/Ninja/ninja.exe" "C:/Qt/Tools/Ninja_64/ninja.exe")
    if(DEFINED ENV{{VCPKG_ROOT}})
        file(GLOB _vcpkg_ninja "$ENV{{VCPKG_ROOT}}/downloads/tools/ninja-*/ninja.exe")
        list(APPEND _ninja_candidates ${{_vcpkg_ninja}})
    endif()
    foreach(_n IN LISTS _ninja_candidates)
        if(EXISTS "${{_n}}")
            set(CMAKE_MAKE_PROGRAM "${{_n}}" CACHE FILEPATH "Ninja (auto-detected)")
            break()
        endif()
    endforeach()
endif()

project({spec.service_name}QtClientGrpcpp VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED Qt6_DIR AND DEFINED ENV{{Qt6_DIR}})
    set(Qt6_DIR "$ENV{{Qt6_DIR}}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{{QT_DIR}} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{{QT_DIR}}")
endif()
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network Concurrent)

if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE
   AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE
        "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
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
set(_proto_path "${{CMAKE_CURRENT_SOURCE_DIR}}/proto")
set(_gen_dir    "${{CMAKE_CURRENT_BINARY_DIR}}/grpc_gen")
file(MAKE_DIRECTORY "${{_gen_dir}}")

set(_proto_files
{proto_files_block})

protobuf_generate(
    LANGUAGE       cpp
    OUT_VAR        PROTO_SRCS
    PROTOS         ${{_proto_files}}
    PROTOC_OUT_DIR "${{_gen_dir}}"
    IMPORT_DIRS    "${{_proto_path}}")

protobuf_generate(
    LANGUAGE             grpc
    OUT_VAR              GRPC_SRCS
    PROTOS               ${{_proto_files}}
    PROTOC_OUT_DIR       "${{_gen_dir}}"
    IMPORT_DIRS          "${{_proto_path}}"
    GENERATE_EXTENSIONS  .grpc.pb.h .grpc.pb.cc
    PLUGIN               "protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>")

qt_add_executable({sn}_qt_gui
    src/main.cpp
    src/MainWindow.cpp
    src/MainWindow.h
    src/MainWindow.ui
    ${{PROTO_SRCS}}
    ${{GRPC_SRCS}})

set(CMAKE_AUTOUIC_SEARCH_PATHS "${{CMAKE_CURRENT_SOURCE_DIR}}/src")

target_include_directories({sn}_qt_gui PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{_gen_dir}}")

target_link_libraries({sn}_qt_gui PRIVATE
    Qt6::Widgets Qt6::Network Qt6::Concurrent
    protobuf::libprotobuf
    gRPC::grpc++)

set_target_properties({sn}_qt_gui PROPERTIES
    WIN32_EXECUTABLE ON MACOSX_BUNDLE ON)

{_MB_DEPLOY_RUNTIME_BLOCK}
mb_deploy_runtime({sn}_qt_gui QT_APP)
'''


# -------- Per-service .proto generator (multi_proto fallback) --------
def _mp_gen_proto(svc) -> str:
    """Generate a single .proto for one service when the user didn't
    import a hand-written one.  Same shape as the single-service
    fallback but parameterised on per-service proto package."""
    pkg = _mp_proto_package(svc)
    type_map = {'string': 'string', 'int32': 'int32', 'int64': 'int64',
                'bool': 'bool', 'float': 'float', 'double': 'double',
                'bytes': 'bytes'}
    lines = [
        'syntax = "proto3";',
        '',
        f'package {pkg};',
        '',
        f'service {svc.name} {{',
    ]
    for m in svc.methods:
        stream = "stream " if m.server_streaming else ""
        lines.append(f'  rpc {m.name} ({m.name}Request) returns ({stream}{m.name}Response);')
    lines.append('}')
    lines.append('')
    for m in svc.methods:
        lines.append(f'message {m.name}Request {{')
        for i, p in enumerate(m.params, 1):
            t = type_map.get((p.type or 'string').lower(), 'string')
            lines.append(f'  {t} {p.name} = {i};')
        if not m.params:
            lines.append('  // no parameters')
        lines.append('}')
        lines.append('')
        rt = type_map.get((m.return_type or 'string').lower(), 'string')
        lines.append(f'message {m.name}Response {{')
        lines.append(f'  {rt} value = 1;')
        lines.append('}')
        lines.append('')
    return '\n'.join(lines)


# -------- Settings (shared by all services in this binary) --------
def _mp_settings_h(spec) -> str:
    sn = spec.snake_name
    prefix = sn.upper() + "_"
    return f'''#pragma once

#include "MicroserviceBase/Settings.h"

// Shared settings for the {spec.service_name} multi-service binary.
// All hosted gRPC services use ONE Consul registration, ONE port, ONE
// service name (read from env via the {prefix} prefix).

namespace {sn} {{

struct Settings : public microservice_base::BaseServiceSettings {{
    Settings() {{
        service_name = "{sn}";
        loadBaseFromEnv("{prefix}");
    }}
}};

}}  // namespace {sn}
'''


# -------- main.cpp registers ALL services on one ServerBuilder --------
def _mp_main_cpp(spec, services) -> str:
    sn = spec.snake_name
    includes = []
    instances = []
    adapters = []
    add_calls = []
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        svc_pascal = svc.name
        ns = _mp_proto_namespace(svc)
        pkg = _mp_proto_package(svc)
        includes.append(f'#include "{svc_snake}/domain/{svc_pascal}.h"')
        includes.append(f'#include "{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.h"')
        instances.append(
            f'        {svc_snake}::{svc_pascal} {svc_snake}Domain;'
        )
        adapters.append(
            f'        {svc_snake}::{svc_pascal}GrpcAdapter '
            f'{svc_snake}Adapter({svc_snake}Domain);'
        )
        add_calls.append(
            f'        runner.addService(&{svc_snake}Adapter, '
            f'"{pkg}.{svc_pascal}");'
        )

    inc_block = '\n'.join(includes)
    inst_block = '\n'.join(instances)
    adapt_block = '\n'.join(adapters)
    add_block = '\n'.join(add_calls)

    return f'''#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
{inc_block}

// Multi-proto / single-binary entry point.  This process hosts
// {len(services)} gRPC services on one port, with one Consul
// registration.  Shutdown signals deregister all services together.

int main() {{
    try {{
        {sn}::Settings settings;

        // Domain instances (pure business logic, no gRPC dependency).
{inst_block}

        // Adapter instances (gRPC service implementations wrapping domain).
{adapt_block}

        microservice_base::ServiceRunner runner(settings, {{"v1"}});
{add_block}
        runner.serveForever();
    }} catch (const std::exception& e) {{
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }}
    return 0;
}}
'''


# -------- Per-service domain --------
def _mp_domain_h(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    method_hints = "\n".join(
        f"    // rpc {m.name}(...)  -  wire in adapters/api/{svc_pascal}GrpcAdapter.cpp"
        for m in svc.methods
    ) or "    // (no methods declared in proto yet)"
    return f'''#pragma once

// Domain layer for {svc.name}.
// Pure C++ — no gRPC, no Consul.

#include <string>

namespace {svc_snake} {{

class {svc_pascal} {{
public:
    // TODO: add your methods here.  Expected API surface:
{method_hints}
}};

}}  // namespace {svc_snake}
'''


def _mp_domain_cpp(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    return f'''#include "{svc_pascal}.h"

namespace {svc_snake} {{

// TODO: implement your domain methods here.
// (Empty body — class is currently a placeholder.)

}}  // namespace {svc_snake}
'''


# -------- Per-service gRPC adapter --------
def _mp_input_cpp_type(m, ns_fallback: str) -> str:
    """C++ fully-qualified request type for an RPC method.

    Imported .protos pre-populate ``m.input_type`` with the FQ proto type
    name (e.g. ``Com_Setup_Device.InterfaceTypeRequest``) -- convert dots
    to ``::`` and prefix ``::`` so it's anchored at the global ns.

    When ``input_type`` is empty (wizard-defined methods, no .proto
    import), fall back to the ``<MethodName>Request`` convention used
    by the auto-generated _mp_gen_proto fallback.
    """
    if getattr(m, "input_type", "") and m.input_type.strip():
        return "::" + m.input_type.strip().replace(".", "::")
    return f"::{ns_fallback}::{m.name}Request"


def _mp_output_cpp_type(m, ns_fallback: str) -> str:
    if getattr(m, "output_type", "") and m.output_type.strip():
        return "::" + m.output_type.strip().replace(".", "::")
    return f"::{ns_fallback}::{m.name}Response"


def _mp_adapter_h(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    basename = _mp_proto_basename(svc)
    ns = _mp_proto_namespace(svc)
    method_decls = "\n".join(
        f'    grpc::Status {m.name}(grpc::ServerContext* ctx,\n'
        f'        const {_mp_input_cpp_type(m, ns)}* request,\n'
        f'        {_mp_output_cpp_type(m, ns)}* response) override;'
        for m in svc.methods
    )
    return f'''#pragma once

#include "{basename}.grpc.pb.h"
#include "../../domain/{svc_pascal}.h"

namespace {svc_snake} {{

// gRPC adapter: thin wrapper translating proto messages <-> domain calls.
class {svc_pascal}GrpcAdapter final
    : public ::{ns}::{svc_pascal}::Service {{
public:
    explicit {svc_pascal}GrpcAdapter({svc_pascal}& domain) : m_domain(domain) {{}}

{method_decls}

private:
    {svc_pascal}& m_domain;
}};

}}  // namespace {svc_snake}
'''


def _mp_adapter_cpp(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    svc_pascal = svc.name
    ns = _mp_proto_namespace(svc)
    method_impls = "\n\n".join(
        f'grpc::Status {svc_pascal}GrpcAdapter::{m.name}(\n'
        f'    grpc::ServerContext* /*ctx*/,\n'
        f'    const {_mp_input_cpp_type(m, ns)}* /*request*/,\n'
        f'    {_mp_output_cpp_type(m, ns)}* /*response*/) {{\n'
        f'    // TODO: read fields from `request`, call m_domain, populate `response`.\n'
        f'    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement {m.name}");\n'
        f'}}'
        for m in svc.methods
    )
    return f'''#include "{svc_pascal}GrpcAdapter.h"

namespace {svc_snake} {{

{method_impls}

}}  // namespace {svc_snake}
'''


# -------- CMakeLists: N proto codegens + 1 add_executable --------
def _mp_cmake(spec, services) -> str:
    sn = spec.snake_name
    project_name = spec.service_name

    # Build the per-proto codegen blocks (auto-generated mode) and the
    # source-list expansion for the single executable.  Dedup by basename
    # so single-file multi-service multi_proto (all services share one
    # .proto) doesn't emit duplicate add_custom_command -> same outputs,
    # which CMake rejects.
    codegen_blocks = []
    proto_src_lists = []
    proto_inc_dirs = set()
    seen_basenames = set()
    for svc in services:
        basename = _mp_proto_basename(svc)
        if basename in seen_basenames:
            continue
        seen_basenames.add(basename)
        proto_filename = _mp_proto_filename(svc)
        var = basename.upper() + "_SRCS"
        proto_src_lists.append(f"${{{var}}}")
        codegen_blocks.append(_mp_proto_codegen_block(proto_filename, basename, var))
    codegen_joined = '\n'.join(codegen_blocks)
    proto_srcs_var_uses = '\n    '.join(proto_src_lists)

    # Per-service source list.  Include .h files alongside .cpp so they
    # appear in Qt Creator's project view -- CMake's project model only
    # surfaces files listed as target sources, so headers omitted here
    # are invisible in the tree (build-wise irrelevant, but bad UX).
    per_svc_srcs = ['    src/Settings.h']
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        svc_pascal = svc.name
        per_svc_srcs.append(f'    src/{svc_snake}/domain/{svc_pascal}.h')
        per_svc_srcs.append(f'    src/{svc_snake}/domain/{svc_pascal}.cpp')
        per_svc_srcs.append(f'    src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.h')
        per_svc_srcs.append(f'    src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.cpp')
    per_svc_block = '\n'.join(per_svc_srcs)

    return f'''cmake_minimum_required(VERSION 3.16)

# vcpkg auto-detection BEFORE project() so the toolchain loads correctly.
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "{project_name}: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.  Set VCPKG_ROOT or pass "
        "-DCMAKE_TOOLCHAIN_FILE=... directly.")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (auto-set from triplets/ overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/triplets"
            CACHE PATH "vcpkg overlay triplets directory")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/ports"
            CACHE PATH "vcpkg overlay ports directory")
    endif()
endif()

project({project_name} VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Manifest-mode fallback: when vcpkg toolchain didn't load but a populated
# vcpkg_installed/x64-mingw-qt/ exists in the build dir.
if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()
if(NOT Protobuf_PROTOC_EXECUTABLE
   AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE
        "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
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
    if(DEFINED ENV{{MICROSERVICEBASE_DIR}})
        list(APPEND _mb_candidates
            "$ENV{{MICROSERVICEBASE_DIR}}/MicroserviceBase/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}/runtime_cpp"
            "$ENV{{MICROSERVICEBASE_DIR}}")
    endif()
    list(APPEND _mb_candidates
        "${{CMAKE_CURRENT_SOURCE_DIR}}/../../MicroserviceBase/runtime_cpp")
    set(_mb_in_tree "")
    foreach(_p IN LISTS _mb_candidates)
        if(EXISTS "${{_p}}/CMakeLists.txt")
            set(_mb_in_tree "${{_p}}")
            break()
        endif()
    endforeach()
    if(_mb_in_tree)
        add_subdirectory("${{_mb_in_tree}}"
                         "${{CMAKE_CURRENT_BINARY_DIR}}/microservice_base_runtime")
    else()
        message(FATAL_ERROR
            "MicroserviceBase runtime not found.  Set MICROSERVICEBASE_DIR env var "
            "to your framework checkout, or install + add to CMAKE_PREFIX_PATH "
            "(see docs/runtime_cpp_install.md).")
    endif()
endif()

{_MB_DEPLOY_RUNTIME_BLOCK}

# ---- Proto codegen (one block per .proto file) -----------------------
set(PROTO_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/proto")
set(GEN_DIR "${{CMAKE_CURRENT_BINARY_DIR}}/gen")
file(MAKE_DIRECTORY "${{GEN_DIR}}")
if(TARGET protobuf::protoc)
    get_target_property(_protoc protobuf::protoc LOCATION)
else()
    find_program(_protoc NAMES protoc protoc.exe
        HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/protobuf"
              "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf"
        REQUIRED)
endif()
if(TARGET gRPC::grpc_cpp_plugin)
    get_target_property(_grpc_cpp gRPC::grpc_cpp_plugin LOCATION)
else()
    find_program(_grpc_cpp NAMES grpc_cpp_plugin grpc_cpp_plugin.exe
        HINTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-windows/tools/grpc"
              "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/grpc"
        REQUIRED)
endif()

{codegen_joined}

# ---- Single executable hosting all services --------------------------
add_executable({sn}
    src/main.cpp
{per_svc_block}
    {proto_srcs_var_uses}
)

target_include_directories({sn} PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{GEN_DIR}}"
)

target_link_libraries({sn} PRIVATE
    microservice_base::runtime
    gRPC::grpc++ ${{GRPC_REFL_LIB}}
    protobuf::libprotobuf
)
mb_deploy_runtime({sn})

# ---- On-demand `dist` target ----
# Builds the .exe (if not already built) then runs deploy_qt_vcpkg.bat
# to package a self-contained dist-qt-vcpkg/ folder.  Invoke from CLI:
#   cmake --build <build-dir> --target dist
# In Qt Creator: Projects -> Build -> Build Steps -> Add "CMake Build" step
# with Targets = "dist".  Doesn't fire on F5 / Build All -- only when
# explicitly requested -- so day-to-day builds stay snappy.
if(WIN32 AND EXISTS "${{CMAKE_SOURCE_DIR}}/deploy_qt_vcpkg.bat")
    add_custom_target(dist
        COMMAND "${{CMAKE_SOURCE_DIR}}/deploy_qt_vcpkg.bat"
        WORKING_DIRECTORY "${{CMAKE_SOURCE_DIR}}"
        DEPENDS {sn}
        COMMENT "[mb-dist] Packaging dist-qt-vcpkg/ via deploy_qt_vcpkg.bat"
        USES_TERMINAL
        VERBATIM)
endif()
'''


def _mp_proto_codegen_block(proto_filename: str, basename: str, var: str) -> str:
    """Emit the add_custom_command + variable for one .proto's codegen.

    Quoting note: with VERBATIM, embedded quotes inside an argument value
    (e.g. `--proto_path="${PROTO_DIR}"`) get passed to protoc as part of
    the path literal -- protoc then sees `"D:/path"` (with quotes) and
    reports `directory does not exist`.  The fix is to drop the inner
    quotes; VERBATIM still escapes spaces correctly for paths containing
    spaces because each argument is passed as one element.
    """
    return f'''add_custom_command(
    OUTPUT
        "${{GEN_DIR}}/{basename}.pb.cc"  "${{GEN_DIR}}/{basename}.pb.h"
        "${{GEN_DIR}}/{basename}.grpc.pb.cc" "${{GEN_DIR}}/{basename}.grpc.pb.h"
    COMMAND ${{_protoc}}
        --proto_path=${{PROTO_DIR}}
        --cpp_out=${{GEN_DIR}}
        --grpc_out=${{GEN_DIR}}
        --plugin=protoc-gen-grpc=${{_grpc_cpp}}
        ${{PROTO_DIR}}/{proto_filename}
    DEPENDS "${{PROTO_DIR}}/{proto_filename}"
    COMMENT "Generating gRPC stubs for {proto_filename}"
    VERBATIM)
set({var}
    "${{GEN_DIR}}/{basename}.pb.cc"
    "${{GEN_DIR}}/{basename}.grpc.pb.cc")'''


# -------- Nomad job (one job, one .exe, one port) --------
def _mp_nomad(spec, services) -> str:
    sn = spec.snake_name
    prefix = sn.upper() + "_"
    services_list = ", ".join(svc.name for svc in services)
    # NOTE: NO `service { ... }` block here.
    # Consul registration is performed by the C++ ServiceRunner at startup
    # (HTTP API call to Consul agent).  Nomad's service block validates
    # service names against RFC 1123 (alphanumeric + dashes only) which
    # rejects snake_case names like "multi_service".  Letting the runtime
    # handle registration sidesteps that AND keeps registration / health
    # check / shutdown deregister atomic with the process lifecycle.
    return f'''# Nomad job for {spec.service_name}.
# Hosts {len(services)} gRPC service(s) in one process: {services_list}.
# Single port, single Consul registration (done by ServiceRunner at startup).

job "{sn}" {{
  datacenters = ["{spec.nomad_dc}"]
  type        = "service"

  group "{sn}" {{
    count = 1

    network {{
      port "grpc" {{}}   # dynamic port — Nomad picks a free one
    }}

    task "server" {{
      driver = "{spec.nomad_driver}"

      # Windows: launch via run_{sn}.bat (emitted by deploy_qt_vcpkg.bat
      # into dist-qt-vcpkg/).  The .bat sets PATH so vcpkg/MinGW DLLs
      # resolve regardless of which agent inherits which environment.
      # The `dist-msys2` segment is a placeholder -- deploy_qt_vcpkg.bat
      # rewrites the project path AND swaps dist-msys2 -> dist-qt-vcpkg
      # when copying this HCL into dist-qt-vcpkg/deploy/.
      # Path placeholder uses ONE segment after `C:/path/to/` so
      # prep_nomad_paths.bat's regex `C:/path/to/[^/]+` matches it.
      config {{
        command = "cmd.exe"
        args    = ["/c", "C:/path/to/{spec.service_name}/dist-msys2/run_{sn}.bat"]
      }}

      # On Linux drop the cmd.exe wrapper and run the binary directly:
      # config {{
      #   command = "/path/to/{sn}"
      # }}

      env {{
        {prefix}GRPC_PORT      = "${{NOMAD_PORT_grpc}}"
        {prefix}ADVERTISE_ADDR = "127.0.0.1"
        {prefix}CONSUL_ADDR    = "{spec.nomad_consul_addr}"
        {prefix}LOG_LEVEL      = "INFO"
      }}

      resources {{
        cpu    = {spec.nomad_cpu}
        memory = {spec.nomad_mem}
      }}
    }}
  }}
}}
'''


# -------- Build scripts (single .exe — simpler than monorepo's N-exe loop) --------
def _mp_build_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
:: Build the {spec.service_name} multi-service binary.
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
call "%SCRIPT_DIR%\\set_env.bat"
cmake -S "%SCRIPT_DIR%" -B "%SCRIPT_DIR%\\build" -G Ninja ^
    -DCMAKE_BUILD_TYPE=Release || exit /b 1
cmake --build "%SCRIPT_DIR%\\build" --config Release || exit /b 1
echo [build] OK -^> %SCRIPT_DIR%\\build\\{sn}.exe
endlocal
'''


def _mp_build_sh(spec) -> str:
    sn = spec.snake_name
    return f'''#!/usr/bin/env bash
# Build the {spec.service_name} multi-service binary.
set -e
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"
cmake -S "$SCRIPT_DIR" -B "$SCRIPT_DIR/build" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$SCRIPT_DIR/build" --config Release
echo "[build] OK -> $SCRIPT_DIR/build/{sn}"
'''


# -------- Stub-gen helpers (walk all .proto files in proto/) --------
def _mp_gen_stubs_bat(spec, services) -> str:
    proto_list = " ".join(_mp_proto_filename(svc) for svc in services)
    return f'''@echo off
:: Generate C++ proto + grpc stubs for all .proto files.
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
where protoc >nul 2>&1 || ( echo [stubs] ERROR: protoc not in PATH & exit /b 1 )
where grpc_cpp_plugin >nul 2>&1 || ( echo [stubs] ERROR: grpc_cpp_plugin not in PATH & exit /b 1 )
for %%P in ({proto_list}) do (
    echo [stubs] %%P
    protoc --proto_path="%SCRIPT_DIR%" --cpp_out="%SCRIPT_DIR%" --grpc_out="%SCRIPT_DIR%" ^
        --plugin=protoc-gen-grpc="%~dp0..\\..\\grpc_cpp_plugin.exe" ^
        "%SCRIPT_DIR%\\%%P" || exit /b 1
)
echo [stubs] Done.
endlocal
'''


def _mp_gen_stubs_sh(spec, services) -> str:
    proto_list = " ".join(_mp_proto_filename(svc) for svc in services)
    return f'''#!/usr/bin/env bash
# Generate C++ proto + grpc stubs for all .proto files.
set -e
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
for proto in {proto_list}; do
    echo "[stubs] $proto"
    protoc --proto_path="$SCRIPT_DIR" --cpp_out="$SCRIPT_DIR" --grpc_out="$SCRIPT_DIR" \\
        --plugin=protoc-gen-grpc="$(which grpc_cpp_plugin)" \\
        "$SCRIPT_DIR/$proto"
done
echo "[stubs] Done."
'''


# -------- README --------
def _mp_readme(spec, services) -> str:
    sn = spec.snake_name
    svc_lines = "\n".join(
        f"- **{svc.name}** — proto `{_mp_proto_filename(svc)}`, "
        f"package `{_mp_proto_package(svc)}`, "
        f"{len(svc.methods)} method(s)"
        for svc in services
    )

    # Annotated folder tree.  Mark user-editable spots with [edit] so a
    # new contributor can find where their work goes vs. what to leave alone.
    svc_tree_lines = []
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        svc_pascal = svc.name
        svc_tree_lines.append(
            f"│   ├── {svc_snake}/                "
            f"# {svc_pascal} (proto `{_mp_proto_filename(svc)}`)"
        )
        svc_tree_lines.append(
            f"│   │   ├── domain/{svc_pascal}.{{h,cpp}}"
            f"      # [edit] business logic (pure C++)"
        )
        svc_tree_lines.append(
            f"│   │   └── adapters/api/{svc_pascal}GrpcAdapter.{{h,cpp}}"
            f"  # [edit] proto<->domain wrapper"
        )
    svc_tree = "\n".join(svc_tree_lines)

    return f'''# {spec.service_name}

{spec.description or spec.service_name + ' multi-service binary.'}

**Layout**: `multi_proto` — {len(services)} gRPC services hosted in ONE
binary, ONE Consul registration, ONE port (vehicle-example pattern).

## Hosted services

{svc_lines}

## Folder structure

`[edit]` marks files you'll write business logic into.  Everything else
is scaffolding regenerated by `mb-scaffold` — safe to leave alone.

```
{spec.service_name}/
├── proto/                       # N .proto files (one per service, each with its own package)
{chr(10).join(f"│   ├── {_mp_proto_filename(svc)}" for svc in services)}
├── src/
│   ├── main.cpp                 # registers ALL services on one ServerBuilder
│   ├── Settings.h               # shared config (env prefix {sn.upper()}_)
{svc_tree}
├── deploy/{sn}.nomad.hcl  # Nomad job (single .exe, dynamic port)
├── client/                      # console client subproject
│   ├── src/client.cpp           # interactive RPC tester (Consul or --direct)
│   └── CMakeLists.txt
├── CMakeLists.txt               # one add_executable, N proto codegens
├── build_deploy.bat / .sh       # one-shot build for the server binary
├── set_env*.bat / .sh           # toolchain env (VCPKG_ROOT, QT_DIR, etc.)
└── README.md
```

## Build & run flow

```mermaid
flowchart TD
    Start([Start])
    Setup["1\\. One-time setup<br/>setx VCPKG_ROOT, QT_DIR, QT_MINGW_BIN"]
    Choose{{"Toolchain?"}}
    Prebuilt{{"Have prebuilt zip?"}}
    Import["import_prebuilt.bat &lt;zip&gt;<br/>~30 seconds"]
    BuildVcpkg["build_qt_vcpkg.bat<br/>(or Qt Creator F5)"]
    BuildMSYS2["build_deploy_msys2.bat"]
    BuildResult["build-qt-vcpkg/{sn}.exe<br/>+ runtime DLLs alongside"]
    LocalRun["Run locally:<br/>{sn}.exe"]
    Pkg["deploy_qt_vcpkg.bat<br/>→ dist-qt-vcpkg/"]
    NomadRun["nomad job run<br/>deploy/{sn}.nomad.hcl"]
    Discover["Clients discover via Consul<br/>(svc name: {sn})"]

    Start --> Setup --> Choose
    Choose -->|"Qt MinGW + vcpkg<br/>(recommended)"| Prebuilt
    Choose -->|MSYS2| BuildMSYS2 --> BuildResult
    Prebuilt -->|"Yes (~2 min total)"| Import --> BuildVcpkg
    Prebuilt -->|"No (first build ~30-60 min)"| BuildVcpkg
    BuildVcpkg --> BuildResult
    BuildResult --> LocalRun
    BuildResult -->|For sharing| Pkg
    LocalRun --> NomadRun
    Pkg --> NomadRun
    NomadRun --> Discover
```

## Build (quick)

```cmd
build_deploy.bat        :: Windows MSYS2 path
build_qt_vcpkg.bat      :: Windows Qt MinGW + vcpkg path
./build_deploy.sh       # Linux
```

Output: one executable `build*/{sn}.exe` listening on
`${sn.upper()}_GRPC_PORT` (Nomad-allocated when run under Nomad).
gRPC server reflection enumerates every hosted service so generic
clients (Manager GUI, `grpcurl`) discover them transparently.

## Why multi_proto vs. monorepo

Use **multi_proto** (this layout) when the services are:
- conceptually one device with multiple functional surfaces
  (e.g. PowerSupply: configuration + control), AND
- always co-deployed (one binary, one process), AND
- benefit from sharing a Consul registration / port / lifecycle.

Use **monorepo** when services are independent enough to be deployed
separately (each gets its own .exe, its own Consul registration,
its own port).
'''


# =======================================================================
# Qt-native client (qt_client/) — uses Qt6::Grpc + Qt6::Protobuf
# =======================================================================
#
# Emitted when spec.gui_type != "none" AND spec.client_grpc_kind == "qt".
#
# This is a *separate* CMake project under qt_client/ — it does NOT
# add_subdirectory the MicroserviceBase runtime, does NOT pull in Google
# grpc++.  It can be built with the Qt-installer MinGW toolchain
# (e.g. C:\Qt\6.11.0\mingw_64) without ABI conflicts against the MSYS2-
# built server, because the server and client never share a binary.
#
# The same .proto is copied verbatim into qt_client/proto/ so the user
# can build the Qt project independently (e.g. on a different machine).
# Wire-protocol interop with the Google grpc server is automatic — they
# both speak the same gRPC HTTP/2 dialect.

def _qt_client_files(spec, services) -> Dict[str, str]:
    """Emit a parallel Qt-native client project under ``qt_client/``.

    ``services`` is the monorepo service list; pass ``None`` for a
    single-service scaffold.  In single-service mode the proto's lone
    service is what the GUI exposes; in monorepo mode the GUI's service
    picker dispatches to whichever service the user selects.
    """
    sn = spec.snake_name
    pkg = spec.proto_package
    files: Dict[str, str] = {}

    # ---- Copy the .proto so the Qt project is buildable on its own ----
    files[f"qt_client/proto/{sn}.proto"] = (
        spec.proto_content_override or "// Run the parent project's proto generator first.\n")

    files["qt_client/CMakeLists.txt"]       = _qt_client_cmake(spec, services)
    files["qt_client/src/main.cpp"]         = _qt_client_main_cpp(spec)
    files["qt_client/src/MainWindow.h"]     = _qt_client_mainwindow_h()
    files["qt_client/src/MainWindow.cpp"]   = _qt_client_mainwindow_cpp(spec, services)
    # Qt Designer-editable form file — AUTOUIC generates ui_MainWindow.h
    # from this at build time.
    files["qt_client/src/MainWindow.ui"]    = _qt_client_mainwindow_ui(spec)
    files["qt_client/build_qt.bat"]         = _qt_client_build_bat(spec)
    files["qt_client/build_qt.sh"]          = _qt_client_build_sh(spec)
    # build_deploy_qt.{bat,sh}: configure + build + windeployqt + run
    # launcher.  Produces a self-contained dist-qt/ folder portable
    # across Windows machines without a Qt install on the target.
    files["qt_client/build_deploy_qt.bat"]  = _qt_client_build_deploy_bat(spec)
    files["qt_client/build_deploy_qt.sh"]   = _qt_client_build_deploy_sh(spec)
    # One-shot pre-generation of Qt-style stubs into proto/ — same
    # protoc command CMake runs at build time, just standalone.
    files["qt_client/proto/generate_qt_stubs.bat"] = _qt_client_gen_stubs_bat(spec)
    files["qt_client/proto/generate_qt_stubs.sh"]  = _qt_client_gen_stubs_sh(spec)
    files["qt_client/README.md"]            = _qt_client_readme(spec, services)
    return files


def _qt_client_cmake(spec, services) -> str:
    sn = spec.snake_name
    project = f"{spec.service_name}QtClient"
    return f'''cmake_minimum_required(VERSION 3.16)
project({project} VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Qt 6 discovery — honour both Qt6_DIR (cmake config dir) and QT_DIR
# (Qt install prefix), so users can point this anywhere from the env
# without touching CMakeLists.
if(NOT DEFINED Qt6_DIR AND DEFINED ENV{{Qt6_DIR}})
    set(Qt6_DIR "$ENV{{Qt6_DIR}}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{{QT_DIR}} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{{QT_DIR}}")
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
    if(DEFINED ENV{{PROTOC_DIR}})
        list(APPEND _protoc_candidates
            "$ENV{{PROTOC_DIR}}/protoc.exe"
            "$ENV{{PROTOC_DIR}}/protoc")
    endif()
    list(APPEND _protoc_candidates
        "C:/msys64/mingw64/bin/protoc.exe"
        "C:/msys64/ucrt64/bin/protoc.exe")
    if(DEFINED ENV{{VCPKG_ROOT}})
        list(APPEND _protoc_candidates
            "$ENV{{VCPKG_ROOT}}/installed/x64-windows/tools/protobuf/protoc.exe")
    endif()
    foreach(_c IN LISTS _protoc_candidates)
        if(EXISTS "${{_c}}")
            set(Protobuf_PROTOC_EXECUTABLE "${{_c}}"
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
    message(STATUS "Using protoc: ${{Protobuf_PROTOC_EXECUTABLE}}")
    get_filename_component(_protoc_dir "${{Protobuf_PROTOC_EXECUTABLE}}" DIRECTORY)
    set(ENV{{PATH}} "${{_protoc_dir}};$ENV{{PATH}}")

    get_filename_component(_protoc_prefix "${{_protoc_dir}}/.." ABSOLUTE)
    list(APPEND CMAKE_PREFIX_PATH "${{_protoc_prefix}}")
    message(STATUS "Adding to CMAKE_PREFIX_PATH for Protobuf headers/libs: ${{_protoc_prefix}}")
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

{_MB_DEPLOY_RUNTIME_BLOCK}

qt_add_executable({sn}_qt_gui
    src/main.cpp
    src/MainWindow.cpp
    src/MainWindow.h
    src/MainWindow.ui)

# Make AUTOUIC look in src/ for the .ui file
set(CMAKE_AUTOUIC_SEARCH_PATHS "${{CMAKE_CURRENT_SOURCE_DIR}}/src")

# Generate Qt-style protobuf message classes (QProtobufMessage subclasses).
# OUTPUT_DIRECTORY MUST live under the build tree — writing generated
# `*.qpb.{{h,cpp}}` back into the source tree causes ninja to detect the
# source dir as "dirty" on every build and re-run cmake forever
# ("manifest 'build.ninja' still dirty after 100 tries").  IDEs pick up
# the generated headers via compile_commands.json / the target's include
# dirs.  proto/generate_qt_stubs.bat runs the same protoc command
# outside CMake for one-shot pre-generation if you want to browse stubs
# alongside the .proto source.
qt_add_protobuf({sn}_qt_gui
    PROTO_FILES proto/{sn}.proto
    OUTPUT_DIRECTORY "${{CMAKE_CURRENT_BINARY_DIR}}/qt_proto_gen")

# Generate Qt-style gRPC client stubs (no SERVER variant — Qt 6 doesn't
# provide one; the service is built with Google grpc++ separately).
qt_add_grpc({sn}_qt_gui CLIENT
    PROTO_FILES proto/{sn}.proto
    OUTPUT_DIRECTORY "${{CMAKE_CURRENT_BINARY_DIR}}/qt_proto_gen")

target_include_directories({sn}_qt_gui PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{CMAKE_CURRENT_BINARY_DIR}}/qt_proto_gen")

target_link_libraries({sn}_qt_gui PRIVATE
    Qt6::Widgets
    Qt6::Network
    Qt6::Grpc
    Qt6::Protobuf
    Qt6::ProtobufWellKnownTypes)

set_target_properties({sn}_qt_gui PROPERTIES
    WIN32_EXECUTABLE ON
    MACOSX_BUNDLE    ON)

mb_deploy_runtime({sn}_qt_gui QT_APP)
'''


def _qt_client_main_cpp(spec) -> str:
    return '''#include <QApplication>
#include "MainWindow.h"

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);
    MainWindow w;
    w.show();
    return app.exec();
}
'''


def _qt_client_mainwindow_h() -> str:
    return '''#pragma once

#include <QHash>
#include <QStringList>
#include <QUrl>
#include <QWidget>

#include <functional>
#include <memory>

#include <QtGrpc/QGrpcCallReply>
#include <QtGrpc/QGrpcStatus>
#include <QtProtobuf/QProtobufJsonSerializer>

QT_BEGIN_NAMESPACE
namespace Ui { class MainWindow; }
class QNetworkAccessManager;
QT_END_NAMESPACE

class QGrpcHttp2Channel;

class MainWindow : public QWidget {
    Q_OBJECT
public:
    using DoneFn   = std::function<void(bool ok, const QString& body)>;
    using InvokeFn = std::function<void(const QByteArray& jsonReq, DoneFn done)>;

    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

private slots:
    void onConnectClicked();
    void onSendClicked();
    void onServiceChanged(int);
    void onUseConsulToggled(bool checked);

private:
    /// Build the gRPC channel for `url` and re-attach every typed Client.
    void applyChannelUrl(const QUrl& url);
    /// Resolve the service name via Consul HTTP API → host:port → applyChannelUrl.
    void resolveViaConsul();
    void setupDispatch();

    /// JSON in -> typed Request -> typed RPC -> typed Response -> JSON out.
    /// Called from each (service, method) lambda in setupDispatch().  All
    /// JSON / status / error boilerplate lives here, so adding an RPC is
    /// one new line.
    template <class Req, class Resp, class CallFn>
    void invokeRpc(const QByteArray& jsonReq, DoneFn done, CallFn&& callRpc) {
        QProtobufJsonSerializer json;
        Req req;
        const QByteArray body = jsonReq.trimmed().isEmpty()
                                ? QByteArray("{}") : jsonReq;
        if (!req.deserialize(&json, body)) {
            done(false, QStringLiteral("Failed to parse request JSON"));
            return;
        }
        // Qt 6.8+: client RPCs return std::unique_ptr<QGrpcCallReply>.
        // Capture the raw pointer for connect() and *move* the unique_ptr
        // into the slot lambda so the reply lives until the signal fires.
        auto reply = callRpc(req);
        auto* raw  = reply.get();
        connect(raw, &QGrpcCallReply::finished, this,
            [r = std::move(reply), done](const QGrpcStatus& st) {
                if (!st.isOk()) {
                    done(false, QStringLiteral("RPC failed: ") + st.message());
                    return;
                }
                // Qt 6.8+: read<T>() returns std::optional<T>.  `template`
                // disambiguator required because Resp is a dependent type.
                auto resp = r->template read<Resp>();
                if (!resp) {
                    done(false, QStringLiteral("Failed to read response"));
                    return;
                }
                QProtobufJsonSerializer s;
                done(true, QString::fromUtf8(resp->serialize(&s)));
            });
    }

    Ui::MainWindow* ui;
    QNetworkAccessManager* m_net = nullptr;
    std::shared_ptr<QGrpcHttp2Channel> m_channel;

    /// "Service.Method" -> typed dispatcher.
    QHash<QString, InvokeFn> m_dispatch;
    /// "Service" -> ordered method names.
    QHash<QString, QStringList> m_methodsByService;
    QStringList m_serviceList;
};
'''


def _qt_client_mainwindow_ui(spec) -> str:
    """Qt Designer-editable .ui file — defines the form layout that
    ``ui->setupUi(this)`` instantiates at runtime.  AUTOUIC generates
    ``ui_MainWindow.h`` from this at build time."""
    title = f"{spec.service_name} (Qt Client)"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>MainWindow</class>
 <widget class="QWidget" name="MainWindow">
  <property name="geometry">
   <rect><x>0</x><y>0</y><width>820</width><height>560</height></rect>
  </property>
  <property name="windowTitle">
   <string>{title}</string>
  </property>
  <layout class="QVBoxLayout" name="verticalLayout">
   <item>
    <layout class="QHBoxLayout" name="modeRow">
     <item>
      <widget class="QCheckBox" name="useConsul">
       <property name="text"><string>Use Consul (resolve service → host:port)</string></property>
       <property name="checked"><bool>true</bool></property>
      </widget>
     </item>
    </layout>
   </item>
   <item>
    <layout class="QHBoxLayout" name="consulRow">
     <item>
      <widget class="QLabel" name="consulUrlLabel">
       <property name="text"><string>Consul:</string></property>
      </widget>
     </item>
     <item>
      <widget class="QLineEdit" name="consulUrlEdit">
       <property name="text"><string>http://127.0.0.1:8500</string></property>
      </widget>
     </item>
     <item>
      <widget class="QLabel" name="serviceNameLabel">
       <property name="text"><string>Service name:</string></property>
      </widget>
     </item>
     <item>
      <widget class="QLineEdit" name="serviceNameEdit">
       <property name="placeholderText"><string>e.g. analog_input_service</string></property>
      </widget>
     </item>
    </layout>
   </item>
   <item>
    <layout class="QHBoxLayout" name="hostRow">
     <item>
      <widget class="QLabel" name="hostLabel">
       <property name="text"><string>Direct URL:</string></property>
      </widget>
     </item>
     <item>
      <widget class="QLineEdit" name="hostEdit">
       <property name="text"><string>http://127.0.0.1:50051</string></property>
       <property name="enabled"><bool>false</bool></property>
      </widget>
     </item>
     <item>
      <widget class="QPushButton" name="connectButton">
       <property name="text"><string>Connect</string></property>
      </widget>
     </item>
    </layout>
   </item>
   <item>
    <layout class="QHBoxLayout" name="pickRow">
     <item>
      <widget class="QLabel" name="serviceLabel">
       <property name="text"><string>Service:</string></property>
      </widget>
     </item>
     <item>
      <widget class="QComboBox" name="serviceCombo"/>
     </item>
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
    <widget class="QLabel" name="requestLabel">
     <property name="text"><string>Request (JSON):</string></property>
    </widget>
   </item>
   <item>
    <widget class="QPlainTextEdit" name="requestEdit">
     <property name="plainText"><string>{{}}</string></property>
     <property name="placeholderText"><string>JSON body matching the RPC's request message — e.g. {{"channel": 0}}</string></property>
    </widget>
   </item>
   <item>
    <layout class="QHBoxLayout" name="sendRow">
     <item>
      <widget class="QPushButton" name="sendButton">
       <property name="text"><string>Send</string></property>
      </widget>
     </item>
     <item>
      <widget class="QLabel" name="statusLabel">
       <property name="text"><string>(not connected)</string></property>
      </widget>
     </item>
    </layout>
   </item>
   <item>
    <widget class="QLabel" name="responseLabel">
     <property name="text"><string>Response:</string></property>
    </widget>
   </item>
   <item>
    <widget class="QTextEdit" name="responseEdit">
     <property name="readOnly"><bool>true</bool></property>
     <property name="placeholderText"><string>RPC results appear here…</string></property>
    </widget>
   </item>
  </layout>
 </widget>
 <resources/>
 <connections/>
</ui>
'''


def _qt_client_mainwindow_cpp(spec, services) -> str:
    """Generate a MainWindow with a per-(service, method) JSON dispatch
    table.  Each entry parses the JSON request into the typed Qt-style
    Request, fires the RPC, and serialises the typed Response back to
    JSON for display — works uniformly for any .proto without
    per-method hand-coding.

    The dispatch table is populated from spec.methods (single-service)
    or spec.services (monorepo).  Streaming RPCs are rejected with a
    clear message since JSON-roundtrip of streams isn't meaningful.
    """
    sn = spec.snake_name
    ns = spec.proto_namespace

    # Normalise to a list of (display_name, namespace_qualified_class,
    # snake_name, methods).
    entries = []
    if services:
        for s in services:
            entries.append((s.name, f"{ns}::{s.name}",
                            _mono_snake(s.name), s.methods))
    else:
        grpc_name = _grpc_svc_name(spec)
        entries.append((grpc_name, f"{ns}::{grpc_name}",
                        _snake(grpc_name), spec.methods or []))

    # Per-service typed Client accessors in an anonymous namespace.
    accessors = []
    for display, class_, snake, _methods in entries:
        accessors.append(
            f'{class_}::Client& {snake}_client() {{ static {class_}::Client c; return c; }}')
    accessors_block = "\n".join(accessors)

    # Channel re-attach for every cached Client.
    attach_lines = "\n        ".join(
        f'{snake}_client().attachChannel(m_channel);'
        for _, _, snake, _ in entries
    )

    # Dispatch + serviceList + methodsByService body for setupDispatch().
    dispatch_blocks = []
    for display, class_, snake, methods in entries:
        method_labels = ", ".join(f'"{m.name}"' for m in methods)
        dispatch_blocks.append(
            f'    m_serviceList << "{display}";\n'
            f'    m_methodsByService["{display}"] = {{ {method_labels} }};')
        for m in methods:
            inT  = ("::" + m.input_type.replace(".", "::"))  if m.input_type  else f"{ns}::{m.name}Request"
            outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"
            if m.server_streaming:
                dispatch_blocks.append(
                    f'    m_dispatch.insert("{display}.{m.name}",\n'
                    f'        [](const QByteArray&, DoneFn d) {{\n'
                    f'            d(false, "{m.name}: streaming RPCs not supported by JSON UI client.");\n'
                    f'        }});')
            else:
                dispatch_blocks.append(
                    f'    m_dispatch.insert("{display}.{m.name}",\n'
                    f'        [this](const QByteArray& j, DoneFn d) {{\n'
                    f'            invokeRpc<{inT}, {outT}>(j, d,\n'
                    f'                [](const {inT}& r) {{ return {snake}_client().{m.name}(r); }});\n'
                    f'        }});')
    dispatch_body = "\n\n".join(dispatch_blocks)

    return f'''#include "MainWindow.h"
#include "ui_MainWindow.h"   // generated by AUTOUIC from MainWindow.ui

// Qt-style protobuf + gRPC stubs generated by qt_add_protobuf and
// qt_add_grpc(... CLIENT) (CMake) or proto/generate_qt_stubs.bat
// (one-shot).  File names follow `<.proto stem>.qpb.h` and
// `<stem>_client.grpc.qpb.h`.
#include "{sn}.qpb.h"
#include "{sn}_client.grpc.qpb.h"

// Qt 6.8+: the URL goes directly to QGrpcHttp2Channel's ctor;
// QGrpcChannelOptions is no longer the URL container — it just carries
// per-channel tweaks like deadline / metadata.
#include <QtGrpc/QGrpcHttp2Channel>

#include <QCheckBox>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLineEdit>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStringList>
#include <QTextEdit>
#include <QUrl>

namespace {{

// One typed Client per service, kept alive for the lifetime of the
// process.  Each Client is stateless except for its attached channel;
// we re-attach in applyChannelUrl() whenever the user clicks Connect.
{accessors_block}

}}  // namespace

MainWindow::MainWindow(QWidget* parent)
    : QWidget(parent), ui(new Ui::MainWindow), m_net(new QNetworkAccessManager(this)) {{
    ui->setupUi(this);

    setupDispatch();

    for (const auto& s : m_serviceList) ui->serviceCombo->addItem(s);
    onServiceChanged(0);

    // Default the Consul service-name field to the first service in
    // the picker (saves a paste).
    if (!m_serviceList.isEmpty())
        ui->serviceNameEdit->setText(m_serviceList.first().toLower().replace(' ', '_'));

    connect(ui->connectButton, &QPushButton::clicked, this, &MainWindow::onConnectClicked);
    connect(ui->sendButton,    &QPushButton::clicked, this, &MainWindow::onSendClicked);
    connect(ui->serviceCombo,  QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWindow::onServiceChanged);
    connect(ui->useConsul,     &QCheckBox::toggled, this, &MainWindow::onUseConsulToggled);
    onUseConsulToggled(ui->useConsul->isChecked());
}}

MainWindow::~MainWindow() {{
    delete ui;
}}

void MainWindow::onServiceChanged(int) {{
    ui->methodCombo->clear();
    for (const auto& m : m_methodsByService.value(ui->serviceCombo->currentText()))
        ui->methodCombo->addItem(m);
}}

void MainWindow::onUseConsulToggled(bool checked) {{
    ui->consulUrlEdit->setEnabled(checked);
    ui->serviceNameEdit->setEnabled(checked);
    ui->hostEdit->setEnabled(!checked);
}}

void MainWindow::onConnectClicked() {{
    if (ui->useConsul->isChecked()) {{
        resolveViaConsul();
    }} else {{
        applyChannelUrl(QUrl(ui->hostEdit->text()));
    }}
}}

void MainWindow::resolveViaConsul() {{
    const QString consul = ui->consulUrlEdit->text().trimmed();
    const QString svc    = ui->serviceNameEdit->text().trimmed();
    if (consul.isEmpty() || svc.isEmpty()) {{
        ui->statusLabel->setText("Consul URL and service name are required.");
        return;
    }}
    QUrl url(consul + "/v1/health/service/" + svc + "?passing=true");
    ui->statusLabel->setText(QStringLiteral("Resolving %1 via Consul...").arg(svc));

    auto* reply = m_net->get(QNetworkRequest(url));
    connect(reply, &QNetworkReply::finished, this, [this, reply, svc]() {{
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {{
            ui->statusLabel->setText(
                QStringLiteral("Consul error: %1").arg(reply->errorString()));
            return;
        }}
        QJsonParseError perr;
        const QJsonDocument doc = QJsonDocument::fromJson(reply->readAll(), &perr);
        if (perr.error != QJsonParseError::NoError || !doc.isArray()) {{
            ui->statusLabel->setText("Consul returned non-JSON or non-array.");
            return;
        }}
        const QJsonArray arr = doc.array();
        if (arr.isEmpty()) {{
            ui->statusLabel->setText(
                QStringLiteral("No healthy '%1' registered in Consul.").arg(svc));
            return;
        }}
        // Pick the first healthy entry.  Production would round-robin.
        const QJsonObject entry   = arr.first().toObject();
        const QJsonObject service = entry.value("Service").toObject();
        QString addr = service.value("Address").toString();
        if (addr.isEmpty())
            addr = entry.value("Node").toObject().value("Address").toString();
        const int port = service.value("Port").toInt();
        if (addr.isEmpty() || port <= 0) {{
            ui->statusLabel->setText("Consul entry missing Address / Port.");
            return;
        }}
        const QUrl target(QStringLiteral("http://%1:%2").arg(addr).arg(port));
        ui->hostEdit->setText(target.toString());   // surface for visibility
        applyChannelUrl(target);
    }});
}}

void MainWindow::applyChannelUrl(const QUrl& url) {{
    // Qt 6.8+: pass the URL directly.  Add a QGrpcChannelOptions arg
    // for deadline / metadata tweaks if you need them.
    m_channel = std::make_shared<QGrpcHttp2Channel>(url);
    if (!m_channel) {{
        ui->statusLabel->setText("channel failed");
        return;
    }}
    // Re-attach every typed client to the new channel.
    {attach_lines}
    ui->statusLabel->setText(QStringLiteral("channel ready: %1").arg(url.toString()));
}}

void MainWindow::onSendClicked() {{
    if (!m_channel) {{
        ui->statusLabel->setText("Click Connect first.");
        return;
    }}
    const QString svc = ui->serviceCombo->currentText();
    const QString rpc = ui->methodCombo->currentText();
    const QString key = svc + QChar('.') + rpc;
    const QByteArray body = ui->requestEdit->toPlainText().toUtf8();

    auto it = m_dispatch.find(key);
    if (it == m_dispatch.end()) {{
        ui->statusLabel->setText(QStringLiteral("No dispatcher for %1").arg(key));
        return;
    }}

    ui->statusLabel->setText(QStringLiteral("Calling %1 ...").arg(key));
    ui->responseEdit->clear();
    it.value()(body, [this](bool ok, const QString& result) {{
        ui->responseEdit->setPlainText(result);
        ui->statusLabel->setText(ok ? "OK" : "FAILED");
    }});
}}

// =======================================================================
// Dispatch table — one lambda per (service, method) pair.
//
// Each lambda calls invokeRpc<Req, Resp>(...) with a small inner lambda
// that returns the typed Client's reply.  invokeRpc handles JSON parse,
// signal hookup, response read, JSON serialize.  Adding a method = one
// new line; no boilerplate is repeated.
// =======================================================================

void MainWindow::setupDispatch() {{
{dispatch_body}
}}
'''


def _qt_client_build_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
:: Build the Qt-native client using the Qt-installer toolchain.
::
:: Honoured env vars (override any of these before invoking):
::   QT_DIR    Qt install prefix.  Default: C:\\Qt\\6.11.0\\mingw_64
::   QT_TOOLS  Qt Tools root.       Default: C:\\Qt\\Tools
::             (provides bundled CMake + Ninja + MinGW compiler)

setlocal EnableDelayedExpansion
if not defined QT_DIR   set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"
if not defined QT_TOOLS set "QT_TOOLS=C:\\Qt\\Tools"
if not defined Qt6_DIR  set "Qt6_DIR=%QT_DIR%\\lib\\cmake\\Qt6"

:: Qt-bundled MinGW compiler — fall back through the versions Qt has shipped.
set "MINGW="
for %%V in (mingw1310_64 mingw1120_64 mingw900_64 mingw810_64) do (
    if not defined MINGW if exist "%QT_TOOLS%\\%%V\\bin\\g++.exe" (
        set "MINGW=%QT_TOOLS%\\%%V\\bin"
    )
)

:: Qt-bundled CMake — folder name varies (CMake_64 on most installs).
set "QTCMAKE="
for %%C in (CMake_64 CMake) do (
    if not defined QTCMAKE if exist "%QT_TOOLS%\\%%C\\bin\\cmake.exe" (
        set "QTCMAKE=%QT_TOOLS%\\%%C\\bin"
    )
)

:: Qt-bundled Ninja.
set "QTNINJA="
if exist "%QT_TOOLS%\\Ninja\\ninja.exe" set "QTNINJA=%QT_TOOLS%\\Ninja"

if defined MINGW   set "PATH=%MINGW%;%PATH%"
if defined QTCMAKE set "PATH=%QTCMAKE%;%PATH%"
if defined QTNINJA set "PATH=%QTNINJA%;%PATH%"
set "PATH=%QT_DIR%\\bin;%PATH%"

:: Qt's qt_add_grpc / qt_add_protobuf invoke Google's `protoc` at build
:: time (Qt only ships the Qt-side plugins).  The Qt installer doesn't
:: bundle protoc, so we look for one from common installs.  PROTOC_DIR
:: (env var) wins if explicitly set.
set "PROTOC_DIR_FOUND="
if defined PROTOC_DIR if exist "%PROTOC_DIR%\\protoc.exe" set "PROTOC_DIR_FOUND=%PROTOC_DIR%"
if not defined PROTOC_DIR_FOUND if exist "C:\\msys64\\mingw64\\bin\\protoc.exe" set "PROTOC_DIR_FOUND=C:\\msys64\\mingw64\\bin"
if not defined PROTOC_DIR_FOUND if defined VCPKG_ROOT if exist "%VCPKG_ROOT%\\installed\\x64-windows\\tools\\protobuf\\protoc.exe" set "PROTOC_DIR_FOUND=%VCPKG_ROOT%\\installed\\x64-windows\\tools\\protobuf"
if defined PROTOC_DIR_FOUND set "PATH=%PATH%;%PROTOC_DIR_FOUND%"

where protoc >nul 2>&1 || (
    echo ERROR: 'protoc' executable not found on PATH.
    echo        Qt's qt_add_grpc / qt_add_protobuf needs Google's protoc
    echo        at build time.  Easiest fix on Windows:
    echo            pacman -S mingw-w64-x86_64-protobuf  ^(via MSYS2^)
    echo        ...or download a release from
    echo            https://github.com/protocolbuffers/protobuf/releases
    echo        and either put protoc.exe on PATH or
    echo            set "PROTOC_DIR=C:\\path\\to\\folder\\containing\\protoc.exe"
    echo        before re-running this script.
    exit /b 1
)

:: Hard requirement: a Qt-bundled MinGW.  Refuse to fall back to a random
:: g++ on PATH (Strawberry Perl, msys64, mingw-w64 standalone, …) — those
:: ABIs don't match Qt's prebuilt libs and you'd hit cryptic link errors.
if not defined MINGW (
    echo ERROR: No Qt-bundled MinGW found under %%QT_TOOLS%%.
    echo        Open Qt Maintenance Tool -^> Add or remove components,
    echo        and tick exactly one of:
    echo            Qt -^> Tools -^> MinGW 13.1.0 64-bit
    echo            Qt -^> Tools -^> MinGW 11.2.0 64-bit
    exit /b 1
)
if not defined QTCMAKE (
    echo ERROR: cmake not found.  Install it via the Qt Maintenance Tool:
    echo   Qt -^> Tools -^> CMake     ^(typically C:\\Qt\\Tools\\CMake_64^)
    exit /b 1
)
if not defined QTNINJA (
    echo ERROR: ninja not found.  Install it via the Qt Maintenance Tool:
    echo   Qt -^> Tools -^> Ninja     ^(typically C:\\Qt\\Tools\\Ninja^)
    exit /b 1
)

:: Sanity-check the Qt install before invoking CMake.  This gives a
:: clearer error than CMake's "Could not find Qt6" stack trace.
if not exist "%QT_DIR%\\lib\\cmake\\Qt6\\Qt6Config.cmake" (
    echo ERROR: Qt6 not found at %%QT_DIR%% = %QT_DIR%
    echo        Expected: %QT_DIR%\\lib\\cmake\\Qt6\\Qt6Config.cmake
    echo        Set QT_DIR to the actual install prefix, e.g.:
    echo            set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"
    echo        or check your install with: dir C:\\Qt\\
    exit /b 1
)
if not exist "%QT_DIR%\\lib\\cmake\\Qt6Grpc\\Qt6GrpcConfig.cmake" (
    echo ERROR: Qt6 GRPC module not installed at %%QT_DIR%%.
    echo        Open Qt Maintenance Tool -^> Add or remove components,
    echo        select your Qt version, and tick:
    echo            Qt GRPC                 ^(stable in 6.8+, Tech Preview in 6.7^)
    echo            Qt Protobuf
    echo            Qt Protobuf Well Known Types
    exit /b 1
)

set "BUILD=%~dp0build-qt"
if not exist "%BUILD%" mkdir "%BUILD%"
cd /d "%BUILD%"

echo Using:
echo   QT_DIR  = %QT_DIR%
echo   MINGW   = %MINGW%
echo   CMake   = %QTCMAKE%
echo   Ninja   = %QTNINJA%
echo.

:: Pass the toolchain explicitly so PATH ordering can't matter.
cmake -G "Ninja" ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_PREFIX_PATH="%QT_DIR%" ^
    -DCMAKE_C_COMPILER="%MINGW:\\=/%/gcc.exe" ^
    -DCMAKE_CXX_COMPILER="%MINGW:\\=/%/g++.exe" ^
    -DCMAKE_MAKE_PROGRAM="%QTNINJA:\\=/%/ninja.exe" ^
    ..
if errorlevel 1 ( echo Configure failed. & exit /b 1 )
cmake --build .
if errorlevel 1 ( echo Build failed. & exit /b 1 )

echo.
echo Qt client built: %BUILD%\\{sn}_qt_gui.exe
endlocal
'''


def _qt_client_build_sh(spec) -> str:
    sn = spec.snake_name
    return f'''#!/usr/bin/env bash
# Build the Qt-native client.  Set QT_DIR to your Qt install prefix
# (one that contains bin/qmake6, lib/cmake/Qt6, …).

set -euo pipefail
: "${{QT_DIR:?Set QT_DIR to the Qt install prefix (e.g. /opt/Qt/6.11.0/gcc_64)}}"
export Qt6_DIR="${{Qt6_DIR:-$QT_DIR/lib/cmake/Qt6}}"

BUILD="$(dirname "$(readlink -f "$0")")/build-qt"
mkdir -p "$BUILD"
cd "$BUILD"

cmake -G Ninja -DCMAKE_BUILD_TYPE=Release ..
cmake --build .

echo "Qt client built: $BUILD/{sn}_qt_gui"
'''


def _qt_client_build_deploy_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
:: Build + deploy the Qt-native client into a self-contained dist-qt/
:: folder.  Output:
::   dist-qt\\{sn}_qt_gui.exe          (the binary)
::   dist-qt\\Qt6Core.dll, ...           (Qt runtime, via windeployqt)
::   dist-qt\\platforms\\qwindows.dll    (Qt platform plugin)
::   dist-qt\\libstdc++-6.dll, ...       (MinGW runtime, via windeployqt --compiler-runtime)
::   dist-qt\\run_{sn}_qt_gui.bat      (launcher with QT_PLUGIN_PATH fallback)
::
:: The dist-qt/ folder is portable — copy it to another Windows machine
:: (no Qt install needed on the target) and run the launcher.

setlocal EnableDelayedExpansion

if not defined QT_DIR   set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"
if not defined QT_TOOLS set "QT_TOOLS=C:\\Qt\\Tools"

set "EXE_NAME={sn}_qt_gui.exe"
set "BUILD=%~dp0build-qt"
set "DIST=%~dp0dist-qt"

:: ----- Step 1: configure + build (delegate to build_qt.bat) -----
call "%~dp0build_qt.bat"
if errorlevel 1 (
    echo Build failed; aborting deploy.
    exit /b 1
)

if not exist "%BUILD%\\%EXE_NAME%" (
    echo ERROR: %BUILD%\\%EXE_NAME% not found after build.
    exit /b 1
)

:: ----- Step 2: copy the binary -----
if not exist "%DIST%" mkdir "%DIST%"
xcopy /Y /Q "%BUILD%\\%EXE_NAME%" "%DIST%\\" >nul

:: ----- Step 3: windeployqt — copies Qt DLLs + platform plugin + MinGW runtime -----
set "WINDEPLOYQT="
for %%C in (windeployqt-qt6.exe windeployqt.exe) do (
    if not defined WINDEPLOYQT if exist "%QT_DIR%\\bin\\%%C" set "WINDEPLOYQT=%QT_DIR%\\bin\\%%C"
)
if defined WINDEPLOYQT (
    echo Running !WINDEPLOYQT! ...
    "!WINDEPLOYQT!" --release --no-translations --no-system-d3d-compiler --no-opengl-sw --compiler-runtime "%DIST%\\%EXE_NAME%"
    if errorlevel 1 (
        echo WARNING: windeployqt returned non-zero; the binary may still run if Qt is on PATH.
    )
) else (
    echo WARNING: windeployqt not found under %QT_DIR%\\bin\\
    echo          The exe will only run if Qt's bin and plugins folders are on PATH / QT_PLUGIN_PATH.
)

:: ----- Step 4: launcher .bat with QT_PLUGIN_PATH belt-and-braces fallback -----
> "%DIST%\\run_{sn}_qt_gui.bat" echo @echo off
>> "%DIST%\\run_{sn}_qt_gui.bat" echo if not defined QT_PLUGIN_PATH set "QT_PLUGIN_PATH=%QT_DIR%\\plugins"
>> "%DIST%\\run_{sn}_qt_gui.bat" echo if not defined QML2_IMPORT_PATH set "QML2_IMPORT_PATH=%QT_DIR%\\qml"
>> "%DIST%\\run_{sn}_qt_gui.bat" echo "%%~dp0%EXE_NAME%" %%*

echo.
echo Qt client deployed.  Output:
echo    %DIST%\\%EXE_NAME%
echo Run via:
echo    %DIST%\\run_{sn}_qt_gui.bat
echo The dist-qt folder is portable to other Windows machines (no Qt install needed there).
endlocal
'''


def _qt_client_build_deploy_sh(spec) -> str:
    sn = spec.snake_name
    return f'''#!/usr/bin/env bash
# Build + deploy the Qt-native client into dist-qt/.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
: "${{QT_DIR:?Set QT_DIR to your Qt install prefix}}"

BUILD="$SCRIPT_DIR/build-qt"
DIST="$SCRIPT_DIR/dist-qt"
EXE_NAME="{sn}_qt_gui"

"$SCRIPT_DIR/build_qt.sh"
[[ -f "$BUILD/$EXE_NAME" ]] || {{ echo "Binary not found at $BUILD/$EXE_NAME"; exit 1; }}

mkdir -p "$DIST"
cp -f "$BUILD/$EXE_NAME" "$DIST/"

if [[ "$OSTYPE" == "linux-gnu"* ]] && command -v linuxdeployqt >/dev/null; then
    linuxdeployqt "$DIST/$EXE_NAME" -bundle-non-qt-libs
elif [[ "$OSTYPE" == "darwin"* ]]; then
    "$QT_DIR/bin/macdeployqt" "$DIST/$EXE_NAME.app" || true
fi

echo "Qt client deployed: $DIST/$EXE_NAME"
echo "On Linux you may need: export LD_LIBRARY_PATH=\\"$QT_DIR/lib\\""
'''


def _qt_client_gen_stubs_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
:: Pre-generate Qt6::Protobuf + Qt6::Grpc client stubs from
:: {sn}.proto into THIS folder.
::
:: Output:
::   {sn}.qpb.h / .cpp
::   {sn}_client.grpc.qpb.h / .cpp
::
:: Honoured env vars:
::   QT_DIR       Qt install prefix.  Default: C:\\Qt\\6.11.0\\mingw_64
::   PROTOC_DIR   Folder containing protoc.exe (defaults to MSYS2 / vcpkg / PATH).

setlocal EnableDelayedExpansion
if not defined QT_DIR set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"

set "PROTO_DIR=%~dp0"
if "%PROTO_DIR:~-1%"=="\\" set "PROTO_DIR=%PROTO_DIR:~0,-1%"

set "PROTOC="
if defined PROTOC_DIR if exist "%PROTOC_DIR%\\protoc.exe" set "PROTOC=%PROTOC_DIR%\\protoc.exe"
if not defined PROTOC if exist "C:\\msys64\\mingw64\\bin\\protoc.exe" set "PROTOC=C:\\msys64\\mingw64\\bin\\protoc.exe"
if not defined PROTOC if defined VCPKG_ROOT if exist "%VCPKG_ROOT%\\installed\\x64-windows\\tools\\protobuf\\protoc.exe" set "PROTOC=%VCPKG_ROOT%\\installed\\x64-windows\\tools\\protobuf\\protoc.exe"
if not defined PROTOC for /f "delims=" %%P in ('where protoc 2^>nul') do if not defined PROTOC set "PROTOC=%%P"

if not defined PROTOC (
    echo ERROR: protoc.exe not found.  Install MSYS2's mingw-w64-x86_64-protobuf or set PROTOC_DIR.
    exit /b 1
)

set "QTPB_PLUGIN=%QT_DIR%\\bin\\qtprotobufgen.exe"
set "QTGRPC_PLUGIN=%QT_DIR%\\bin\\qtgrpcgen.exe"
if not exist "%QTPB_PLUGIN%"   ( echo ERROR: qtprotobufgen.exe not found at %QTPB_PLUGIN%   & exit /b 1 )
if not exist "%QTGRPC_PLUGIN%" ( echo ERROR: qtgrpcgen.exe not found at %QTGRPC_PLUGIN%     & exit /b 1 )

echo Using:
echo   protoc        = %PROTOC%
echo   qtprotobufgen = %QTPB_PLUGIN%
echo   qtgrpcgen     = %QTGRPC_PLUGIN%
echo   PROTO_DIR     = %PROTO_DIR%
echo.

"%PROTOC%" ^
    --plugin=protoc-gen-qtprotobuf="%QTPB_PLUGIN%" ^
    --qtprotobuf_out="%PROTO_DIR%" ^
    --proto_path="%PROTO_DIR%" ^
    "%PROTO_DIR%\\{sn}.proto"
if errorlevel 1 ( echo Qt Protobuf generation failed. & exit /b 1 )

"%PROTOC%" ^
    --plugin=protoc-gen-qtgrpc="%QTGRPC_PLUGIN%" ^
    --qtgrpc_opt=GENERATE_PACKAGE_SUBFOLDERS=false ^
    --qtgrpc_out="%PROTO_DIR%" ^
    --proto_path="%PROTO_DIR%" ^
    "%PROTO_DIR%\\{sn}.proto"
if errorlevel 1 ( echo Qt GRPC generation failed. & exit /b 1 )

echo.
echo Qt stubs generated in %PROTO_DIR%
endlocal
'''


def _qt_client_gen_stubs_sh(spec) -> str:
    sn = spec.snake_name
    return f'''#!/usr/bin/env bash
# Pre-generate Qt6::Protobuf + Qt6::Grpc stubs from {sn}.proto.

set -euo pipefail

PROTO_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
: "${{QT_DIR:?Set QT_DIR to your Qt install prefix}}"

PROTOC="${{PROTOC:-$(command -v protoc || true)}}"
[[ -n "$PROTOC" ]] || {{ echo "protoc not found"; exit 1; }}

QTPB_PLUGIN="$QT_DIR/bin/qtprotobufgen"
QTGRPC_PLUGIN="$QT_DIR/bin/qtgrpcgen"
[[ -x "$QTPB_PLUGIN"   ]] || {{ echo "qtprotobufgen not found at $QTPB_PLUGIN"; exit 1; }}
[[ -x "$QTGRPC_PLUGIN" ]] || {{ echo "qtgrpcgen not found at $QTGRPC_PLUGIN"; exit 1; }}

"$PROTOC" \\
    --plugin=protoc-gen-qtprotobuf="$QTPB_PLUGIN" \\
    --qtprotobuf_out="$PROTO_DIR" \\
    --proto_path="$PROTO_DIR" \\
    "$PROTO_DIR/{sn}.proto"

"$PROTOC" \\
    --plugin=protoc-gen-qtgrpc="$QTGRPC_PLUGIN" \\
    --qtgrpc_opt=GENERATE_PACKAGE_SUBFOLDERS=false \\
    --qtgrpc_out="$PROTO_DIR" \\
    --proto_path="$PROTO_DIR" \\
    "$PROTO_DIR/{sn}.proto"

echo "Qt stubs generated in $PROTO_DIR"
'''


def _qt_client_readme(spec, services) -> str:
    sn = spec.snake_name
    if services:
        svc_block = "\n".join(f"- **{s.name}** — {len(s.methods)} RPC method(s)" for s in services)
    else:
        svc_block = f"- **{spec.service_name}** — {len(spec.methods or [])} RPC method(s)"

    return f'''# {spec.service_name} — Qt-native client

Standalone Qt6 GUI client built with **Qt6::Grpc + Qt6::Protobuf**.
Lives in its own CMake project so it can be compiled with the
Qt-installer MinGW toolchain (e.g. `C:\\Qt\\6.11.0\\mingw_64`) without
mixing libraries with the MSYS2-built server.

## Why a separate project?

Qt 6's GRPC/Protobuf modules only provide a **client-side** API — the
service must remain on Google's `grpc::Server` (built via MSYS2 in the
parent project).  Mixing libraries from the two MinGW toolchains in
one binary triggers libstdc++ ABI errors (`nanosleep64`, …), so we
keep them in separate projects, each with its own toolchain.  The two
binaries communicate over the gRPC wire protocol on the same port —
no ABI involved.

## Services available in the GUI

{svc_block}

## Build (Windows)

### Prerequisites — install via Qt Maintenance Tool

Tick all of these under **Add or remove components**:

| Component                                | Why                                                      |
|------------------------------------------|----------------------------------------------------------|
| Qt 6.x.x → **MinGW 13.1.0 64-bit**       | The Qt 6 libraries built with MinGW                      |
| Qt 6.x.x → **Qt GRPC**                   | Client-side gRPC (stable in 6.8+, Tech Preview in 6.7)   |
| Qt 6.x.x → **Qt Protobuf**               | `QProtobufMessage` runtime                               |
| Qt 6.x.x → **Qt Protobuf WellKnownTypes**| `Empty`, `Timestamp`, etc.                               |
| Qt → Tools → **CMake**                   | CMake bundled with Qt                                    |
| Qt → Tools → **Ninja**                   | Build driver                                             |
| Qt → Tools → **MinGW 13.1.0 64-bit**     | The compiler                                             |

### …plus Google's `protoc` (separate from Qt!)

Qt's `qt_add_grpc` / `qt_add_protobuf` invoke **Google's `protoc.exe`** at
build time — Qt only ships the Qt-side code-generation plugins.  The Qt
installer does **not** bundle protoc, so install it separately.  Easiest
options on Windows:

- **MSYS2** (recommended): `pacman -S mingw-w64-x86_64-protobuf` →
  `protoc.exe` lands at `C:\\msys64\\mingw64\\bin\\protoc.exe`.
- **Standalone download** from <https://github.com/protocolbuffers/protobuf/releases>
  (pick a Windows zip, unzip anywhere).

### Build via `build_qt.bat`

```cmd
:: Adjust if your Qt is somewhere else:
set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"

:: Optional — only needed if protoc isn't auto-discovered by CMakeLists:
set "PROTOC_DIR=C:\\msys64\\mingw64\\bin"

build_qt.bat
```

Output: `build-qt\\{sn}_qt_gui.exe`.

### Build via Qt Creator

1. **Open** `qt_client/CMakeLists.txt` → tick the **MinGW 13.1.0 64-bit** kit.
2. *(Only if CMake errors with "protoc not found")* — **Projects → Build →
   CMake → Initial Configuration → Add**:

   | Key                            | Type     | Value                                    |
   |--------------------------------|----------|------------------------------------------|
   | `Protobuf_PROTOC_EXECUTABLE`   | FILEPATH | `C:/msys64/mingw64/bin/protoc.exe`       |

   Then click **Re-configure with Initial Parameters** (CMake caches values, so a regular *Run CMake* won't pick this up).
3. **Build → Build All** (Ctrl+B), **Run** (Ctrl+R).

The bundled `CMakeLists.txt` auto-discovers `protoc` in this order:

1. `-DProtobuf_PROTOC_EXECUTABLE=...` (cache / Qt Creator Initial Config)
2. `PROTOC_DIR` env var → `<PROTOC_DIR>/protoc.exe`
3. `C:/msys64/mingw64/bin/protoc.exe`
4. `<VCPKG_ROOT>/installed/x64-windows/tools/protobuf/protoc.exe`
5. `find_program(protoc)` on PATH

If none match, configuration aborts with a clear error message naming
the override variables — set whichever matches your protoc install.

## Build (Linux / macOS)

```bash
export QT_DIR=/opt/Qt/6.11.0/gcc_64
# Linux: `apt install protobuf-compiler` (or equivalent) usually puts
# protoc on PATH already, so no PROTOC_DIR is needed.
./build_qt.sh
```

## Run

```cmd
build-qt\\{sn}_qt_gui.exe
```

The window has a **Connect** button (defaults to
`http://127.0.0.1:50051`), service / method pickers, and a Send button
that fires the RPC via `QGrpcClient`.  Open
`src/MainWindow.cpp` → `onSendClicked()` and fill in the per-method
dispatch as documented in the inline TODO comment.

## What's generated by the build

- `qt_add_protobuf` produces Qt-style message classes (`QProtobufMessage`
  subclasses) named `<package>::<MessageName>` — with QProperty / setter
  / getter pairs and signal/slot integration.
- `qt_add_grpc(... CLIENT)` produces client classes named
  `<package>::<ServiceName>::Client` whose RPC methods return
  `std::shared_ptr<QGrpcCallReply>`.

These are completely separate from the Google-grpc stubs in the parent
project's `proto/` folder — they don't conflict because they live in a
different binary.
'''


# ===========================================================================
# qt_client_grpcpp/  -  Qt UI client using Google grpc++ via vcpkg.
# Emitted when client_grpc_kind == "google_vcpkg".  Mirrors qt_client/ in
# layout/UX, but uses Google's grpc++ stack (compiled by vcpkg with the
# Qt-installer MinGW toolchain) instead of Qt6::Grpc / Qt6::Protobuf.  The
# point of this variant: client AND server share one toolchain end-to-end
# (Qt 6.x MinGW 13.1.0), and the server's CMakeLists is also re-targeted
# to vcpkg via the shared triplets/ + ports/ overlays at project root.
# ===========================================================================

def _qt_client_grpcpp_files(spec, services) -> Dict[str, str]:
    sn = spec.snake_name
    files: Dict[str, str] = {}
    files[f"qt_client_grpcpp/proto/{sn}.proto"] = (
        spec.proto_content_override or "// Run the parent project's proto generator first.\n")
    files["qt_client_grpcpp/vcpkg.json"]            = _qt_client_grpcpp_vcpkg_json(spec)
    files["qt_client_grpcpp/CMakeLists.txt"]        = _qt_client_grpcpp_cmake(spec)
    files["qt_client_grpcpp/CMakePresets.json"]     = _qt_client_grpcpp_cmake_presets()
    files["qt_client_grpcpp/src/main.cpp"]          = _qt_client_grpcpp_main_cpp(spec)
    files["qt_client_grpcpp/src/MainWindow.h"]      = _qt_client_grpcpp_mainwindow_h(spec)
    files["qt_client_grpcpp/src/MainWindow.cpp"]    = _qt_client_grpcpp_mainwindow_cpp(spec, services)
    files["qt_client_grpcpp/src/MainWindow.ui"]     = _qt_client_mainwindow_ui(spec)
    files["qt_client_grpcpp/build_qt.bat"]          = _qt_client_grpcpp_build_qt_bat(spec)
    files["qt_client_grpcpp/deploy_qt.bat"]         = _qt_client_grpcpp_deploy_qt_bat(spec)
    files["qt_client_grpcpp/export_prebuilt.bat"]   = _qt_client_grpcpp_export_prebuilt_bat(spec)
    files["qt_client_grpcpp/README.md"]             = _qt_client_grpcpp_readme(spec)
    files["qt_client_grpcpp/.gitignore"]            = "build/\nprebuilt/\ndeploy/\n*.user\n"
    return files


def _vcpkg_shared_files(spec) -> Dict[str, str]:
    """Emit shared vcpkg infrastructure at project root (used by both
    server and qt_client_grpcpp/)."""
    return {
        "triplets/x64-mingw-qt.cmake":                          _vcpkg_triplet_main(),
        "triplets/qt-mingw-toolchain.cmake":                    _vcpkg_triplet_chainload(),
        "ports/grpc/00018-gcc13-per-cpu-ice-workaround.patch":  _vcpkg_grpc_ice_patch(),
        "init_vcpkg_overlay.bat":                               _vcpkg_init_overlay_bat(),
        "import_prebuilt.bat":                                  _vcpkg_import_prebuilt_bat(),
        "export_prebuilt.bat":                                  _vcpkg_export_prebuilt_bat(),
        "prep_nomad_paths.bat":                                 _vcpkg_prep_nomad_paths_bat(),
        "CMakePresets.json":                                    _vcpkg_cmake_presets_json(spec),
    }


def _qt_client_grpcpp_vcpkg_json(spec) -> str:
    # vcpkg requires manifest names: lowercase alphanumeric + hyphens only.
    # snake_name has underscores -> swap to hyphens.
    pkg = spec.snake_name.replace('_', '-')
    # `codegen` feature is needed for gRPC::grpc_cpp_plugin imported target
    # (used by protobuf_generate LANGUAGE grpc).
    return ('{\n'
            f'  "name": "{pkg}-qt-client-grpcpp",\n'
            f'  "version-string": "{spec.version}",\n'
            '  "description": "Qt client using Google grpc++ via vcpkg + Qt MinGW.",\n'
            '  "dependencies": [\n'
            '    { "name": "grpc", "default-features": false, "features": ["codegen"] },\n'
            '    "protobuf"\n'
            '  ]\n'
            '}\n')


def _server_vcpkg_json(spec) -> str:
    # vcpkg requires manifest names: lowercase alphanumeric + hyphens only.
    # `codegen` feature is required for gRPC::grpc_cpp_plugin imported
    # target (CMakeLists' proto_block uses it for stub generation).
    # CURL is needed by MicroserviceBase runtime (Consul HTTP registration).
    pkg = spec.snake_name.replace('_', '-')
    return ('{\n'
            f'  "name": "{pkg}-server-vcpkg",\n'
            f'  "version-string": "{spec.version}",\n'
            '  "description": "Server build with Google grpc++ via vcpkg + Qt MinGW.",\n'
            '  "dependencies": [\n'
            '    { "name": "grpc", "default-features": false, "features": ["codegen"] },\n'
            '    "protobuf",\n'
            '    "curl"\n'
            '  ]\n'
            '}\n')


def _vcpkg_triplet_main() -> str:
    return '''# Custom vcpkg triplet pinned to Qt's MinGW 13.1.0 toolchain.
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
'''


def _vcpkg_triplet_chainload() -> str:
    return '''# Chainloaded CMake toolchain - pins compilers to Qt's MinGW 13.1.0.
# Override via env var QT_MINGW_BIN if Qt is installed elsewhere.

set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)

if(DEFINED ENV{QT_MINGW_BIN})
    set(_qt_mingw_bin "$ENV{QT_MINGW_BIN}")
else()
    set(_qt_mingw_bin "C:/Qt/Tools/mingw1310_64/bin")
endif()

if(NOT EXISTS "${_qt_mingw_bin}/g++.exe")
    message(FATAL_ERROR
        "Qt MinGW not found at: ${_qt_mingw_bin}\\n"
        "Set QT_MINGW_BIN env var to your Qt installer's MinGW bin/ folder.")
endif()

set(CMAKE_C_COMPILER   "${_qt_mingw_bin}/gcc.exe")
set(CMAKE_CXX_COMPILER "${_qt_mingw_bin}/g++.exe")
set(CMAKE_RC_COMPILER  "${_qt_mingw_bin}/windres.exe")
set(CMAKE_AR           "${_qt_mingw_bin}/ar.exe"     CACHE FILEPATH "" FORCE)
set(CMAKE_RANLIB       "${_qt_mingw_bin}/ranlib.exe" CACHE FILEPATH "" FORCE)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
'''


def _vcpkg_grpc_ice_patch() -> str:
    # Unified-diff blank context lines must be a literal single-space
    # line, not zero-bytes, or `git apply` rejects with "corrupt patch".
    # Editors/linters strip trailing whitespace from triple-quoted
    # blanks, so we emit a {SP} placeholder and substitute at return.
    return '''From: microservice-base scaffold (google_vcpkg variant)
Subject: [PATCH] Work around gcc 13.1.0 ICE in PerCpu NSDMI

gcc 13.1.0 (Qt 6.x's bundled MinGW kit) crashes with an internal
compiler error when instantiating
  std::unique_ptr<T[]> data_{new T[shards_]}
as a non-static data member initializer inside a class template.
Fixed in gcc 13.3+ but Qt's installer ships exactly 13.1.0.

Move the array allocation into the ctor mem-initializer list -
semantically identical, takes a different front-end path that doesn't ICE.

--- a/src/core/util/per_cpu.h
+++ b/src/core/util/per_cpu.h
@@ -89,7 +89,9 @@ class PerCpu {
  public:
   // Options are not defaulted to try and force consideration of what the
   // options specify.
-  explicit PerCpu(PerCpuOptions options) : shards_(options.Shards()) {}
+  explicit PerCpu(PerCpuOptions options)
+      : shards_(options.Shards()),
+        data_(std::unique_ptr<T[]>(new T[shards_])) {}
{SP}
   T& this_cpu() { return data_[sharding_helper_.GetShardingBits() % shards_]; }
{SP}
@@ -101,7 +103,7 @@ class PerCpu {
  private:
   PerCpuShardingHelper sharding_helper_;
   const size_t shards_;
-  std::unique_ptr<T[]> data_{new T[shards_]};
+  std::unique_ptr<T[]> data_;
 };
{SP}
 }  // namespace grpc_core
'''.replace('{SP}', ' ')


def _vcpkg_init_overlay_bat() -> str:
    return '''@echo off
REM ---------------------------------------------------------------------------
REM init_vcpkg_overlay.bat - setup for the ports/grpc/ overlay.
REM
REM We ship only the gcc 13.1.0 ICE workaround patch; the rest of the
REM grpc port files (portfile.cmake, vcpkg.json, 00001..00017 patches,
REM cmake glue) come from %VCPKG_ROOT%\\ports\\grpc\\.  This script
REM copies them, then patches portfile.cmake (ICE patch line + force
REM gRPC_BUILD_CODEGEN=ON so grpc++_reflection ships).
REM
REM Modes:
REM   (no flag)    Initialise if missing.  No-op if already initialised.
REM   --upgrade    Re-apply all patches in-place (idempotent).  Use this
REM                after pulling a newer mb-scaffold to pick up patch
REM                changes without losing local edits to portfile.cmake.
REM   --reinit     Wipe ports/grpc/ and re-copy + re-patch from scratch.
REM                Use when upstream's vcpkg grpc port changed and you
REM                want the new upstream files.
REM ---------------------------------------------------------------------------
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "OVERLAY=%SCRIPT_DIR%\\ports\\grpc"

REM ---- arg parsing -------------------------------------------------------
set "MODE=init"
if /i "%~1"=="--reinit"  set "MODE=reinit"
if /i "%~1"=="--upgrade" set "MODE=upgrade"
if /i "%~1"=="-r"        set "MODE=reinit"
if /i "%~1"=="-u"        set "MODE=upgrade"
if /i "%~1"=="--help"    goto :help
if /i "%~1"=="-h"        goto :help
if /i "%~1"=="/?"        goto :help

if "%MODE%"=="reinit" (
    echo [init_vcpkg_overlay] --reinit: wiping %OVERLAY%
    rmdir /s /q "%OVERLAY%" 2>nul
    set "MODE=init"
)

if "%MODE%"=="init" (
    if exist "%OVERLAY%\\portfile.cmake" (
        echo [init_vcpkg_overlay] Already initialised: %OVERLAY%\\portfile.cmake
        echo   --upgrade  re-apply patches in place ^(no upstream re-copy^)
        echo   --reinit   wipe + re-copy + re-patch from VCPKG_ROOT
        exit /b 0
    )
    if not defined VCPKG_ROOT (
        echo [init_vcpkg_overlay] ERROR: VCPKG_ROOT is not set.
        echo   setx VCPKG_ROOT C:\\vcpkg
        exit /b 1
    )
    if not exist "%VCPKG_ROOT%\\ports\\grpc\\portfile.cmake" (
        echo [init_vcpkg_overlay] ERROR: %VCPKG_ROOT%\\ports\\grpc not found.
        exit /b 1
    )
    echo [init_vcpkg_overlay] Copying upstream grpc port from %VCPKG_ROOT%\\ports\\grpc
    xcopy /e /y /q "%VCPKG_ROOT%\\ports\\grpc\\*" "%OVERLAY%\\" >nul
)

if not exist "%OVERLAY%\\portfile.cmake" (
    echo [init_vcpkg_overlay] ERROR: %OVERLAY%\\portfile.cmake missing.
    echo   Run without --upgrade first to copy from VCPKG_ROOT.
    exit /b 1
)

REM Patch portfile.cmake.  All edits below are idempotent: the
REM PowerShell guards check whether the change is already present
REM before applying it, so --upgrade can be re-run safely after the
REM init script changes.  Edits:
REM   1. Append 00018 ICE workaround to the PATCHES list.
REM   2. Drop the `codegen` row from vcpkg_check_features so vcpkg's
REM      manifest-mode feature selection can't accidentally turn it off
REM      (it gates upstream's grpc++_reflection target on this flag).
REM   3. Force gRPC_BUILD_CODEGEN=ON via an explicit set() above
REM      vcpkg_cmake_configure and a -D in OPTIONS.  Without this,
REM      gRPC::grpc++_reflection isn't built/installed for the target
REM      triplet and the Manager GUI gets UNIMPLEMENTED on every
REM      reflection RPC.  See examples/docs/html/vcpkg_setup.html.
REM PowerShell (always at System32\\WindowsPowerShell - no Python dep).
echo [init_vcpkg_overlay] Patching portfile.cmake (idempotent: ICE patch + force CODEGEN ON)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = '%OVERLAY%\\portfile.cmake'; $nl = [char]10; $c = Get-Content -Raw -LiteralPath $p; if (-not $c.Contains('00018-gcc13-per-cpu-ice-workaround.patch')) { $m = '00017-add-missing-include-file.patch'; $q = $m + $nl + (' ' * 8) + '00018-gcc13-per-cpu-ice-workaround.patch'; $c = $c.Replace($m, $q) }; $c = $c.Replace('        codegen     gRPC_BUILD_CODEGEN' + $nl, ''); if (-not $c.Contains('set(gRPC_BUILD_CODEGEN ON)')) { $c = $c.Replace('vcpkg_cmake_configure(', '# MicroserviceBase override: force CODEGEN on so grpc++_reflection is built+installed.' + $nl + 'set(gRPC_BUILD_CODEGEN ON)' + $nl + $nl + 'vcpkg_cmake_configure(') }; if (-not $c.Contains('-DgRPC_BUILD_CODEGEN=ON')) { $c = $c.Replace('        -DgRPC_INSTALL=ON', '        -DgRPC_BUILD_CODEGEN=ON' + $nl + '        -DgRPC_INSTALL=ON') }; Set-Content -LiteralPath $p -NoNewline -Value $c"
if errorlevel 1 (
    echo [init_vcpkg_overlay] Failed to patch portfile.cmake.
    exit /b 1
)

echo [init_vcpkg_overlay] Done.  Overlay-port ready at %OVERLAY%
endlocal
exit /b 0

:help
echo Usage: init_vcpkg_overlay.bat [--upgrade^|--reinit]
echo.
echo   (no flag)   Initialise the overlay if missing; no-op otherwise.
echo   --upgrade   Re-apply all patches to the existing portfile.cmake.
echo               Use after pulling a newer mb-scaffold to pick up
echo               patch changes (idempotent, safe to re-run).
echo   --reinit    Wipe ports/grpc/ and re-copy + re-patch from scratch.
echo               Use when upstream's vcpkg grpc port changed and you
echo               want the new upstream files.
exit /b 0
'''


def _vcpkg_import_prebuilt_bat() -> str:
    return '''@echo off
REM Extract a vcpkg_installed_x64-mingw-qt.zip into every build dir of
REM this project (server build-qt-vcpkg/, qt_client_grpcpp/build/, and
REM Qt Creator's build/Desktop_Qt_*/).  Use after a teammate has shared
REM the zip via export_prebuilt.bat - skips the 30-60 min vcpkg compile.
REM
REM Usage:
REM   import_prebuilt.bat <local-path-to-zip>
REM   import_prebuilt.bat <http(s)-url>          (downloads to %TEMP% first)
REM   import_prebuilt.bat                        (prompts interactively)
REM
REM Proxy:
REM   If you're behind a corporate proxy, set HTTPS_PROXY before running:
REM     set HTTPS_PROXY=http://127.0.0.1:3128       (e.g. cntlm)
REM     set HTTP_PROXY=http://127.0.0.1:3128
REM   Both curl and the PowerShell fallback honor HTTPS_PROXY.  Persist with
REM   setx (new shell required) or `set` per-session.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if "%~1"=="" (
    set /p "ZIP_ARG=Enter path or URL to vcpkg_installed_x64-mingw-qt.zip: "
) else (
    REM Use %* (full command line) instead of %~1 because CMD treats =
    REM as a token separator: an unquoted https://x?e=token URL gets
    REM split into %1=https://x?e and %2=token, dropping the auth part.
    set "ZIP_ARG=%*"
)
set "ZIP_ARG=!ZIP_ARG:"=!"
if "!ZIP_ARG!"=="" ( echo [import] ERROR: no zip path/URL. & exit /b 1 )

REM URL or local path?  If http(s), download to %TEMP% first via curl.exe.
set "IS_URL=0"
if /i "!ZIP_ARG:~0,7!"=="http://"  set "IS_URL=1"
if /i "!ZIP_ARG:~0,8!"=="https://" set "IS_URL=1"

set "CURL_EXE=%SystemRoot%\\System32\\curl.exe"
set "TAR_EXE=%SystemRoot%\\System32\\tar.exe"
if not exist "%TAR_EXE%" ( echo [import] ERROR: %TAR_EXE% missing.  Need Win10 1803+. & exit /b 1 )

if "!IS_URL!"=="0" goto :_use_local

if not exist "%CURL_EXE%" ( echo [import] ERROR: %CURL_EXE% missing.  Need Win10 1803+. & exit /b 1 )

REM SharePoint host?  Used to decide whether to (a) auto-append download=1
REM and (b) retry with PowerShell + Windows credentials when curl fails.
set "IS_SHAREPOINT=0"
echo !ZIP_ARG! | findstr /i "sharepoint.com" >nul && set "IS_SHAREPOINT=1"

REM SharePoint share links (/:u:/p/... or /:u:/r/...) serve an HTML
REM viewer page by default.  Append download=1 to force file bytes.
set "DL_URL=!ZIP_ARG!"
if "!IS_SHAREPOINT!"=="1" (
    echo !DL_URL! | findstr /i "download=1" >nul
    if errorlevel 1 (
        REM has query string already?  use & else ?
        echo !DL_URL! | findstr "?" >nul
        if errorlevel 1 ( set "DL_URL=!DL_URL!?download=1" ) else ( set "DL_URL=!DL_URL!&download=1" )
        echo [import] SharePoint link detected - appending download=1
    )
)

set "ZIP_PATH=%TEMP%\\vcpkg_installed_x64-mingw-qt.zip"
echo [import] Downloading: !DL_URL!
echo [import] Saving to  : !ZIP_PATH!

REM Attempt 1: curl.  Honors HTTPS_PROXY/HTTP_PROXY env vars natively
REM (e.g. set HTTPS_PROXY=http://127.0.0.1:3128 for a local cntlm instance).
"%CURL_EXE%" -fL --retry 3 --retry-delay 2 -o "!ZIP_PATH!" "!DL_URL!"
if not errorlevel 1 goto :_post_download

REM Attempt 2 (SharePoint only): PowerShell with -UseDefaultCredentials,
REM which sends the current Windows session's NT/Negotiate creds for SSO.
REM -Proxy honors HTTPS_PROXY (same as curl).  -ProxyUseDefaultCredentials
REM is harmless if proxy doesn't ask for auth (e.g. cntlm relays for us).
if "!IS_SHAREPOINT!"=="1" (
    echo [import] curl failed - retrying via PowerShell with Windows credentials ^(SSO/NTLM^)...
    set "PS_PROXY="
    if not "%HTTPS_PROXY%"=="" set "PS_PROXY=-Proxy '%HTTPS_PROXY%'"
    if "!PS_PROXY!"=="" if not "%HTTP_PROXY%"=="" set "PS_PROXY=-Proxy '%HTTP_PROXY%'"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '!DL_URL!' -UseDefaultCredentials -ProxyUseDefaultCredentials !PS_PROXY! -OutFile '!ZIP_PATH!' -UseBasicParsing -ErrorAction Stop; exit 0 } catch { Write-Host ('  ' + $_.Exception.Message); exit 1 }"
    if not errorlevel 1 goto :_post_download
)

echo [import] ERROR: download failed.
echo [import]        Common causes:
echo [import]          - Tenant requires modern auth ^(no Negotiate^).  Open the
echo [import]            link in a browser, save the file, then re-run with the
echo [import]            local path: import_prebuilt.bat C:\\path\\to\\file.zip
echo [import]          - URL is a share-page URL, not the file.  In SharePoint:
echo [import]            Share -^> Settings -^> Anyone with link, View ^(if policy allows^).
echo [import]          - Corporate proxy blocking the request.
exit /b 1

:_post_download
if not exist "!ZIP_PATH!" ( echo [import] ERROR: download produced no file. & exit /b 1 )

REM Sanity check: did we get a zip or an HTML login/error page?
"%TAR_EXE%" -tf "!ZIP_PATH!" >nul 2>&1
if errorlevel 1 (
    echo [import] ERROR: downloaded file is not a valid zip.
    REM Peek at first 200 bytes so user can diagnose - HTML pages start
    REM with "<!DOCTYPE" or "<html"; sign-in pages mention "login.microsoftonline".
    echo [import] First bytes of downloaded file:
    powershell -NoProfile -Command "Get-Content -LiteralPath '!ZIP_PATH!' -TotalCount 3 -ErrorAction SilentlyContinue | ForEach-Object { '[import]   ' + $_.Substring(0, [Math]::Min(160, $_.Length)) }"
    echo [import]
    echo [import] Most likely cause: SharePoint served a sign-in HTML page
    echo [import] because Bosch SPO requires OAuth ^(Negotiate/NTLM disabled^).
    echo [import] Curl and PowerShell -UseDefaultCredentials can't satisfy this.
    echo [import]
    echo [import] Workarounds, in order of effort:
    echo [import]   1. Download once in your browser ^(you're already signed in^),
    echo [import]      then re-run with the local path:
    echo [import]        import_prebuilt.bat C:\\path\\to\\file.zip
    echo [import]   2. Re-share the file as "Anyone with the link" if Bosch policy
    echo [import]      permits ^(OneDrive: Share -^> Settings -^> Anyone^).  Then this
    echo [import]      script's curl path works without auth.
    echo [import]   3. Host the zip on a fileshare/internal HTTP that doesn't
    echo [import]      require OAuth.
    exit /b 1
)
goto :_have_zip

:_use_local
set "ZIP_PATH=!ZIP_ARG!"
if not exist "!ZIP_PATH!" ( echo [import] ERROR: not found: !ZIP_PATH! & exit /b 1 )

:_have_zip

echo [import] Source zip : !ZIP_PATH!
echo [import] Project    : %SCRIPT_DIR%
set /a "EXTRACTED_COUNT=0"
set "EXTRACTED_TARGETS="
set "WARN_HOST_TOOLS_MISSING=0"

if exist "%SCRIPT_DIR%\\build_qt_vcpkg.bat" (
    call :extract_to "%SCRIPT_DIR%\\build-qt-vcpkg" "server"
)
for /d %%D in ("%SCRIPT_DIR%\\build\\Desktop_Qt_*") do (
    call :extract_to "%%D" "qt-creator-server[%%~nxD]"
)
if exist "%SCRIPT_DIR%\\qt_client_grpcpp\\build_qt.bat" (
    call :extract_to "%SCRIPT_DIR%\\qt_client_grpcpp\\build" "qt-grpcpp-client"
)
REM client/ + qt_client_grpcpp/ when opened standalone in Qt Creator
REM (each gets its own build/Desktop_Qt_*/ subdir).
for /d %%D in ("%SCRIPT_DIR%\\client\\build\\Desktop_Qt_*") do (
    call :extract_to "%%D" "qt-creator-client[%%~nxD]"
)
for /d %%D in ("%SCRIPT_DIR%\\qt_client_grpcpp\\build\\Desktop_Qt_*") do (
    call :extract_to "%%D" "qt-creator-grpcpp[%%~nxD]"
)

if !EXTRACTED_COUNT!==0 (
    echo.
    echo [import] WARN: no build_qt_vcpkg.bat / qt_client_grpcpp\\build_qt.bat /
    echo [import]       build\\Desktop_Qt_* found.  Run from project root.
    exit /b 1
)

echo;
echo [import] Done.  Extracted to !EXTRACTED_COUNT! target(s):!EXTRACTED_TARGETS!
if "!WARN_HOST_TOOLS_MISSING!"=="1" (
    echo;
    echo [import] WARN: host tools missing in zip - x64-windows\\tools\\grpc\\grpc_cpp_plugin.exe.
    echo [import]       Cross-triplet codegen will fail at CMake configure.
    echo [import]       Fix: re-export from a build dir with host tools, then re-import.
)
echo;
echo [import] Next steps:
if exist "%SCRIPT_DIR%\\build_qt_vcpkg.bat" (
    echo   set USE_PREBUILT_VCPKG=1 ^&^& build_qt_vcpkg.bat
)
if exist "%SCRIPT_DIR%\\qt_client_grpcpp\\build_qt.bat" (
    echo   cd qt_client_grpcpp ^&^& set USE_PREBUILT_VCPKG=1 ^&^& build_qt.bat
)
echo   :: Qt Creator: set VCPKG_MANIFEST_INSTALL=OFF in Initial Configuration.
endlocal
goto :eof

:extract_to
set "DEST_PARENT=%~1\\vcpkg_installed"
set "LABEL=%~2"
if exist "%DEST_PARENT%\\x64-mingw-qt"      rmdir /s /q "%DEST_PARENT%\\x64-mingw-qt"
if exist "%DEST_PARENT%\\x64-windows\\tools" rmdir /s /q "%DEST_PARENT%\\x64-windows\\tools"
if not exist "%DEST_PARENT%" mkdir "%DEST_PARENT%"
echo [import] %LABEL%: extracting -^> %DEST_PARENT%
"%TAR_EXE%" -xf "!ZIP_PATH!" -C "%DEST_PARENT%"
if errorlevel 1 ( echo [import] tar failed for %LABEL%. & exit /b 1 )
if not exist "%DEST_PARENT%\\x64-mingw-qt\\share\\grpc" (
    echo [import] WARN: %LABEL%: x64-mingw-qt\\share\\grpc missing - wrong zip?
    exit /b 0
)
if not exist "%DEST_PARENT%\\x64-windows\\tools\\grpc\\grpc_cpp_plugin.exe" (
    set "WARN_HOST_TOOLS_MISSING=1"
)
set /a "EXTRACTED_COUNT+=1"
set "EXTRACTED_TARGETS=!EXTRACTED_TARGETS! !LABEL!"
goto :eof
'''


def _vcpkg_export_prebuilt_bat() -> str:
    return '''@echo off
REM Pack the most-complete vcpkg artifacts from this project's build dirs
REM into prebuilt\\vcpkg_installed_x64-mingw-qt.zip (and the binary cache).
REM Auto-detects the source build dir; override with --source <dir>.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "OUT_DIR=%SCRIPT_DIR%\\prebuilt"

set "SRC="
if /i "%~1"=="--source" ( set "SRC=%~2"
) else if not "%~1"=="" ( set "SRC=%~1" )

if defined SRC (
    if not exist "!SRC!\\vcpkg_installed\\x64-mingw-qt\\share\\grpc" (
        echo [export] ERROR: !SRC!\\vcpkg_installed\\x64-mingw-qt incomplete.
        exit /b 1
    )
    set "INSTALLED_PARENT=!SRC!\\vcpkg_installed"
    set "SRC_LABEL=user-specified"
) else (
    REM Auto-detect order matters: prefer the canonical CLI build dir
    REM (build-qt-vcpkg/) because it's most likely a clean from-source
    REM compile through our overlay-port (with gRPC_BUILD_CODEGEN=ON,
    REM grpc++_reflection, gcc 13 ICE patch).  Qt Creator kit dirs
    REM (build/Desktop_Qt_*/) often contain artifacts imported from a
    REM prebuilt zip OR built with different feature flags -- bad source
    REM for re-export since the receiver might miss reflection / codegen.
    if exist "%SCRIPT_DIR%\\build-qt-vcpkg\\vcpkg_installed\\x64-mingw-qt\\share\\grpc" (
        set "INSTALLED_PARENT=%SCRIPT_DIR%\\build-qt-vcpkg\\vcpkg_installed"
        set "SRC_LABEL=server CLI (build-qt-vcpkg)"
    )
    if not defined INSTALLED_PARENT (
        if exist "%SCRIPT_DIR%\\qt_client_grpcpp\\build\\vcpkg_installed\\x64-mingw-qt\\share\\grpc" (
            set "INSTALLED_PARENT=%SCRIPT_DIR%\\qt_client_grpcpp\\build\\vcpkg_installed"
            set "SRC_LABEL=client CLI (qt_client_grpcpp/build)"
        )
    )
    if not defined INSTALLED_PARENT (
        for /d %%D in ("%SCRIPT_DIR%\\build\\Desktop_Qt_*") do (
            if exist "%%D\\vcpkg_installed\\x64-mingw-qt\\share\\grpc" (
                if not defined INSTALLED_PARENT (
                    set "INSTALLED_PARENT=%%D\\vcpkg_installed"
                    set "SRC_LABEL=Qt Creator (%%~nxD)"
                )
            )
        )
    )
    REM Sanity warning: if we picked a Qt Creator dir, that often means
    REM the user hasn't done a from-source CLI build yet -- their export
    REM may be re-packaging an imported zip rather than fresh artifacts.
    if defined INSTALLED_PARENT (
        echo !INSTALLED_PARENT! | findstr /i "Desktop_Qt_" >nul
        if not errorlevel 1 (
            echo [export] WARN: source is a Qt Creator kit build dir.
            echo [export]       If this came from an import_prebuilt.bat zip, the
            echo [export]       export will just re-pack what was imported.  For a
            echo [export]       fresh from-source build, run build_qt_vcpkg.bat first.
        )
    )
)

if not defined INSTALLED_PARENT (
    echo [export] ERROR: no vcpkg_installed\\x64-mingw-qt found in any build dir.
    exit /b 1
)

set "TAR_EXE=%SystemRoot%\\System32\\tar.exe"
if not exist "%TAR_EXE%" ( echo [export] ERROR: %TAR_EXE% missing. & exit /b 1 )

echo [export] Source : !INSTALLED_PARENT!\\x64-mingw-qt
echo [export] Origin : !SRC_LABEL!
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

REM Pack x64-mingw-qt + only x64-windows/tools/grpc/ (host grpc_cpp_plugin
REM + sibling MSVC runtime DLLs).  protoc has its own copy at x64-mingw-qt/
REM tools/protobuf/ so x64-windows/tools/protobuf/ is redundant.
set "PACK_ARGS=x64-mingw-qt"
if exist "!INSTALLED_PARENT!\\x64-windows\\tools\\grpc" (
    set "PACK_ARGS=!PACK_ARGS! x64-windows\\tools\\grpc"
    echo [export] Including x64-windows\\tools\\grpc - host grpc_cpp_plugin.
) else (
    echo [export] WARN: x64-windows\\tools\\grpc not found - codegen will fail.
)

echo [export] Packing zip...
"%TAR_EXE%" -a -cf "%OUT_DIR%\\vcpkg_installed_x64-mingw-qt.zip" -C "!INSTALLED_PARENT!" !PACK_ARGS!
if errorlevel 1 ( echo [export] tar failed. & exit /b 1 )

set "CACHE_PARENT=%LOCALAPPDATA%\\vcpkg"
if exist "%CACHE_PARENT%\\archives" (
    echo [export] Packing vcpkg binary cache.
    "%TAR_EXE%" -a -cf "%OUT_DIR%\\vcpkg_binary_cache.zip" -C "%CACHE_PARENT%" "archives"
)

echo.
echo [export] Done in %OUT_DIR%:
dir /b "%OUT_DIR%"
echo.
echo [export] Receiving PC: import_prebuilt.bat %%OUT_DIR%%\\vcpkg_installed_x64-mingw-qt.zip
endlocal
'''


def _vcpkg_prep_nomad_paths_bat() -> str:
    return '''@echo off
REM Replace `C:/path/to/<project>` placeholder in deploy\\*.nomad.hcl with
REM the actual absolute path of THIS project (forward-slash form).  Run
REM ONCE after scaffold so Nomad job specs point at the real dist dir.
REM Idempotent.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "DEPLOY_DIR=%SCRIPT_DIR%\\deploy"
set "PROJECT_FWD=%SCRIPT_DIR:\\=/%"

if not exist "%DEPLOY_DIR%\\*.nomad.hcl" (
    echo [prep_nomad] No HCL files in %DEPLOY_DIR% - nothing to do.
    exit /b 0
)

echo [prep_nomad] Updating placeholders in %DEPLOY_DIR%\\*.nomad.hcl
echo [prep_nomad] Replacing C:/path/to/^<project^> -^> %PROJECT_FWD%

for %%H in ("%DEPLOY_DIR%\\*.nomad.hcl") do call :rewrite "%%H"

echo.
echo [prep_nomad] Done.  HCL files now reference: %PROJECT_FWD%/dist-msys2/run_^<svc^>.bat
echo                 (deploy_qt_vcpkg.bat will swap dist-msys2 -^> dist-qt-vcpkg
echo                  in dist-qt-vcpkg\\deploy\\ copies automatically.)
endlocal
goto :eof

:rewrite
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = '%~1'; $c = Get-Content -Raw -LiteralPath $p; $new = $c -replace 'C:/path/to/[^/]+', '%PROJECT_FWD%'; if ($new -ne $c) { Set-Content -LiteralPath $p -NoNewline -Value $new; Write-Host '  - %~nx1 (updated)' } else { Write-Host '  - %~nx1 (no placeholder, skipped)' }"
goto :eof
'''


def _vcpkg_cmake_presets_json(spec) -> str:
    sn = spec.snake_name
    return ('{\n'
            '  "version": 3,\n'
            '  "cmakeMinimumRequired": { "major": 3, "minor": 21 },\n'
            '  "configurePresets": [\n'
            '    {\n'
            '      "name": "vcpkg-x64-mingw-qt",\n'
            '      "displayName": "vcpkg + Qt MinGW 13.1.0 (Release)",\n'
            '      "description": "Builds with vcpkg-installed grpc/protobuf via Qt MinGW. If Qt Creator warns about debugger ABI mismatch, see README \\"Troubleshooting: The ABI of the selected debugger does not match\\".",\n'
            '      "generator": "Ninja",\n'
            f'      "binaryDir": "${{sourceDir}}/build-qt-vcpkg",\n'
            '      "cacheVariables": {\n'
            '        "CMAKE_BUILD_TYPE": "Release",\n'
            '        "CMAKE_TOOLCHAIN_FILE": "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake",\n'
            '        "VCPKG_TARGET_TRIPLET": "x64-mingw-qt",\n'
            '        "VCPKG_OVERLAY_TRIPLETS": "${sourceDir}/triplets",\n'
            '        "VCPKG_OVERLAY_PORTS": "${sourceDir}/ports",\n'
            '        "CMAKE_C_COMPILER": "$env{QT_MINGW_BIN}/gcc.exe",\n'
            '        "CMAKE_CXX_COMPILER": "$env{QT_MINGW_BIN}/g++.exe",\n'
            '        "CMAKE_PREFIX_PATH": "$env{QT_DIR}",\n'
            '        "QT_CREATOR_SKIP_VCPKG_SETUP": "ON"\n'
            '      },\n'
            '      "environment": {\n'
            '        "QT_MINGW_BIN": "C:/Qt/Tools/mingw1310_64/bin",\n'
            '        "QT_DIR":       "C:/Qt/6.11.0/mingw_64"\n'
            '      }\n'
            '    },\n'
            '    {\n'
            '      "name": "vcpkg-x64-mingw-qt-prebuilt",\n'
            '      "displayName": "vcpkg + Qt MinGW (use prebuilt artifacts)",\n'
            '      "description": "Skips vcpkg manifest install.  Drop a prebuilt vcpkg_installed/ in first (e.g. via import_prebuilt.bat).",\n'
            '      "inherits": "vcpkg-x64-mingw-qt",\n'
            '      "cacheVariables": { "VCPKG_MANIFEST_INSTALL": "OFF" }\n'
            '    }\n'
            '  ],\n'
            '  "buildPresets": [\n'
            '    { "name": "vcpkg-x64-mingw-qt",          "configurePreset": "vcpkg-x64-mingw-qt" },\n'
            '    { "name": "vcpkg-x64-mingw-qt-prebuilt", "configurePreset": "vcpkg-x64-mingw-qt-prebuilt" }\n'
            '  ]\n'
            '}\n')


def _qt_client_grpcpp_cmake_presets() -> str:
    """CMakePresets.json for qt_client_grpcpp/.  Mirrors the parent project's
    presets but uses ../triplets and ../ports (overlays live one level up)."""
    return '''{
  "version": 3,
  "cmakeMinimumRequired": { "major": 3, "minor": 21 },
  "configurePresets": [
    {
      "name": "vcpkg-x64-mingw-qt",
      "displayName": "vcpkg + Qt MinGW 13.1.0 (Release)",
      "description": "Builds with vcpkg-installed grpc/protobuf via Qt MinGW.  Overlays from parent project. If Qt Creator warns about debugger ABI mismatch, see parent README \\"Troubleshooting: The ABI of the selected debugger does not match\\".",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_TOOLCHAIN_FILE": "$env{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake",
        "VCPKG_TARGET_TRIPLET": "x64-mingw-qt",
        "VCPKG_OVERLAY_TRIPLETS": "${sourceDir}/../triplets",
        "VCPKG_OVERLAY_PORTS":    "${sourceDir}/../ports",
        "CMAKE_C_COMPILER":   "$env{QT_MINGW_BIN}/gcc.exe",
        "CMAKE_CXX_COMPILER": "$env{QT_MINGW_BIN}/g++.exe",
        "CMAKE_PREFIX_PATH":  "$env{QT_DIR}",
        "QT_CREATOR_SKIP_VCPKG_SETUP": "ON"
      },
      "environment": {
        "QT_MINGW_BIN": "C:/Qt/Tools/mingw1310_64/bin",
        "QT_DIR":       "C:/Qt/6.11.0/mingw_64"
      }
    },
    {
      "name": "vcpkg-x64-mingw-qt-prebuilt",
      "displayName": "vcpkg + Qt MinGW (use prebuilt artifacts)",
      "description": "Skips vcpkg manifest install.  Drop a prebuilt vcpkg_installed/ in first (e.g. via parent's import_prebuilt.bat).",
      "inherits": "vcpkg-x64-mingw-qt",
      "cacheVariables": { "VCPKG_MANIFEST_INSTALL": "OFF" }
    }
  ],
  "buildPresets": [
    { "name": "vcpkg-x64-mingw-qt",          "configurePreset": "vcpkg-x64-mingw-qt" },
    { "name": "vcpkg-x64-mingw-qt-prebuilt", "configurePreset": "vcpkg-x64-mingw-qt-prebuilt" }
  ]
}
'''


def _qt_client_grpcpp_cmake(spec) -> str:
    sn = spec.snake_name
    return f'''cmake_minimum_required(VERSION 3.20)

# vcpkg auto-detection BEFORE project() so the toolchain loads correctly.
# Mirrors the server CMakeLists.txt; overlays live in the PARENT project.
if(NOT CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{{VCPKG_ROOT}})
    set(CMAKE_TOOLCHAIN_FILE "$ENV{{VCPKG_ROOT}}/scripts/buildsystems/vcpkg.cmake"
        CACHE PATH "vcpkg toolchain (auto-detected from VCPKG_ROOT env var)")
elseif(NOT CMAKE_TOOLCHAIN_FILE)
    message(WARNING
        "qt_client_grpcpp: VCPKG_ROOT not set + CMAKE_TOOLCHAIN_FILE missing - "
        "find_package will likely fail.  Set VCPKG_ROOT or pass "
        "-DCMAKE_TOOLCHAIN_FILE=... directly.")
endif()
if(EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets/x64-mingw-qt.cmake")
    if(NOT VCPKG_TARGET_TRIPLET)
        set(VCPKG_TARGET_TRIPLET "x64-mingw-qt"
            CACHE STRING "vcpkg triplet (auto-set from parent's triplets/ overlay)")
    endif()
    if(NOT VCPKG_OVERLAY_TRIPLETS)
        set(VCPKG_OVERLAY_TRIPLETS "${{CMAKE_CURRENT_SOURCE_DIR}}/../triplets"
            CACHE PATH "vcpkg overlay triplets (parent project)")
    endif()
    if(NOT VCPKG_OVERLAY_PORTS AND EXISTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports")
        set(VCPKG_OVERLAY_PORTS "${{CMAKE_CURRENT_SOURCE_DIR}}/../ports"
            CACHE PATH "vcpkg overlay ports (parent project)")
    endif()
endif()
if(NOT DEFINED QT_CREATOR_SKIP_VCPKG_SETUP)
    set(QT_CREATOR_SKIP_VCPKG_SETUP ON CACHE BOOL "")
endif()
if(NOT CMAKE_MAKE_PROGRAM)
    set(_ninja_candidates "C:/Qt/Tools/Ninja/ninja.exe" "C:/Qt/Tools/Ninja_64/ninja.exe")
    if(DEFINED ENV{{VCPKG_ROOT}})
        file(GLOB _vcpkg_ninja "$ENV{{VCPKG_ROOT}}/downloads/tools/ninja-*/ninja.exe")
        list(APPEND _ninja_candidates ${{_vcpkg_ninja}})
    endif()
    foreach(_n IN LISTS _ninja_candidates)
        if(EXISTS "${{_n}}")
            set(CMAKE_MAKE_PROGRAM "${{_n}}" CACHE FILEPATH "Ninja (auto-detected)")
            break()
        endif()
    endforeach()
endif()

project({spec.service_name}QtClientGrpcpp VERSION {spec.version} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED Qt6_DIR AND DEFINED ENV{{Qt6_DIR}})
    set(Qt6_DIR "$ENV{{Qt6_DIR}}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{{QT_DIR}} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{{QT_DIR}}")
endif()
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network Concurrent)

# Manifest-mode fallback: when vcpkg toolchain didn't load (or installed
# without manifest mode), point find_package at the vcpkg_installed dir.
if(EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/share")
    list(APPEND CMAKE_PREFIX_PATH "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt")
endif()

# Pre-set Protobuf_PROTOC_EXECUTABLE so vcpkg's protobuf-cmake-wrapper
# (which hardcodes a search at .../x64-windows/tools/protobuf/) doesn't
# fail when only x64-mingw-qt's tree is present.  Both protoc binaries
# are equivalent; x64-mingw-qt's was built by the same triplet as our libs.
if(NOT Protobuf_PROTOC_EXECUTABLE AND EXISTS "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe")
    set(Protobuf_PROTOC_EXECUTABLE "${{CMAKE_BINARY_DIR}}/vcpkg_installed/x64-mingw-qt/tools/protobuf/protoc.exe"
        CACHE FILEPATH "protoc (target triplet)")
endif()

# Google grpc++ + protobuf via vcpkg (manifest-mode install via toolchain).
find_package(Protobuf CONFIG REQUIRED)
find_package(gRPC     CONFIG REQUIRED)

qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)

# Generate stubs into the build tree (NOT source tree - source-tree codegen
# triggers ninja "manifest still dirty after 100 tries" loops).
set(_proto_path "${{CMAKE_CURRENT_SOURCE_DIR}}/proto")
set(_gen_dir    "${{CMAKE_CURRENT_BINARY_DIR}}/grpc_gen")
file(MAKE_DIRECTORY "${{_gen_dir}}")

set(_proto_files "${{_proto_path}}/{sn}.proto")

protobuf_generate(
    LANGUAGE       cpp
    OUT_VAR        PROTO_SRCS
    PROTOS         ${{_proto_files}}
    PROTOC_OUT_DIR "${{_gen_dir}}"
    IMPORT_DIRS    "${{_proto_path}}")

protobuf_generate(
    LANGUAGE             grpc
    OUT_VAR              GRPC_SRCS
    PROTOS               ${{_proto_files}}
    PROTOC_OUT_DIR       "${{_gen_dir}}"
    IMPORT_DIRS          "${{_proto_path}}"
    GENERATE_EXTENSIONS  .grpc.pb.h .grpc.pb.cc
    PLUGIN               "protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>")

qt_add_executable({sn}_qt_gui
    src/main.cpp
    src/MainWindow.cpp
    src/MainWindow.h
    src/MainWindow.ui
    ${{PROTO_SRCS}}
    ${{GRPC_SRCS}})

set(CMAKE_AUTOUIC_SEARCH_PATHS "${{CMAKE_CURRENT_SOURCE_DIR}}/src")

target_include_directories({sn}_qt_gui PRIVATE
    "${{CMAKE_CURRENT_SOURCE_DIR}}/src"
    "${{_gen_dir}}")

target_link_libraries({sn}_qt_gui PRIVATE
    Qt6::Widgets Qt6::Network Qt6::Concurrent
    protobuf::libprotobuf
    gRPC::grpc++)

set_target_properties({sn}_qt_gui PROPERTIES
    WIN32_EXECUTABLE ON MACOSX_BUNDLE ON)

{_MB_DEPLOY_RUNTIME_BLOCK}
mb_deploy_runtime({sn}_qt_gui QT_APP)
'''


def _qt_client_grpcpp_main_cpp(spec) -> str:
    return '''#include "MainWindow.h"
#include <QApplication>

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    MainWindow w;
    w.show();
    return app.exec();
}
'''


def _qt_client_grpcpp_mainwindow_h(spec, services=None) -> str:
    sn = spec.snake_name

    # multi_proto: each service has its own .proto -> include each one
    # (deduped by basename so single-file multi-service shares one).
    # Single-service / monorepo: one shared proto named after the project.
    if spec.layout == "multi_proto" and services:
        seen = set()
        proto_includes = []
        for svc in services:
            basename = _mp_proto_basename(svc)
            if basename in seen:
                continue
            seen.add(basename)
            proto_includes.append(f'#include "{basename}.pb.h"')
            proto_includes.append(f'#include "{basename}.grpc.pb.h"')
        proto_inc_block = "\n".join(proto_includes)
    else:
        proto_inc_block = f'#include "{sn}.pb.h"\n#include "{sn}.grpc.pb.h"'

    return f'''#pragma once

#include <QWidget>
#include <QHash>
#include <QString>
#include <QByteArray>

#include <functional>
#include <memory>

{proto_inc_block}

namespace Ui {{ class MainWindow; }}
namespace grpc {{ class Channel; }}
class QNetworkAccessManager;

// Inherits QWidget (not QMainWindow) because the .ui file's root is
// <widget class="QWidget">.  Mismatching root class makes setupUi
// drop most child widgets - QMainWindow uses centralWidget/dock layout,
// which conflicts with a plain QVBoxLayout from a QWidget .ui.
class MainWindow : public QWidget {{
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

private slots:
    void onConnectClicked();
    void onSendClicked();
    void onServiceChanged(int);
    void onUseConsulToggled(bool checked);

private:
    using DoneFn  = std::function<void(bool ok, const QString& body)>;
    using DispFn  = std::function<void(const QByteArray&, DoneFn)>;

    void setupDispatch();
    void resolveViaConsul();
    void applyChannelHostPort(const QString& hostport);

    Ui::MainWindow* ui = nullptr;
    QNetworkAccessManager* m_net = nullptr;
    std::shared_ptr<grpc::Channel> m_channel;

    QHash<QString, DispFn> m_dispatch;
    QStringList m_serviceList;
    QHash<QString, QStringList> m_methodsByService;
}};
'''


def _qt_client_grpcpp_mainwindow_cpp(spec, services) -> str:
    """Generate MainWindow.cpp with one dispatch entry per (service, method)
    pair, using Google grpc++ sync stubs on a QtConcurrent::run worker.

    multi_proto: each service has its own proto namespace (parsed from
    its .proto's `package X;`) -- per-service inT/outT must use it.
    Single-service / monorepo: all services share spec.proto_namespace.
    """
    sn = spec.snake_name
    is_multi = spec.layout == "multi_proto"
    project_ns = spec.proto_namespace

    # Each entry: (display_name, fully_qualified_service_class, snake, methods, proto_namespace)
    entries = []
    if services:
        for s in services:
            svc_ns = _mp_proto_namespace(s) if is_multi else project_ns
            entries.append((s.name, f"{svc_ns}::{s.name}", _mono_snake(s.name),
                            s.methods, svc_ns))
    else:
        grpc_name = _grpc_svc_name(spec)
        entries.append((grpc_name, f"{project_ns}::{grpc_name}",
                        _snake(grpc_name), spec.methods or [], project_ns))

    dispatch_blocks = []
    for display, class_, _snake_name, methods, ns in entries:
        method_labels = ", ".join(f'"{m.name}"' for m in methods)
        dispatch_blocks.append(
            f'    m_serviceList << "{display}";\n'
            f'    m_methodsByService["{display}"] = {{ {method_labels} }};')
        for m in methods:
            inT  = ("::" + m.input_type.replace(".", "::"))  if m.input_type  else f"{ns}::{m.name}Request"
            outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"
            if m.server_streaming:
                dispatch_blocks.append(
                    f'    m_dispatch.insert("{display}.{m.name}",\n'
                    f'        [](const QByteArray&, DoneFn d) {{\n'
                    f'            d(false, "{m.name}: streaming RPCs not supported by JSON UI client.");\n'
                    f'        }});')
            else:
                dispatch_blocks.append(
                    f'    m_dispatch.insert("{display}.{m.name}",\n'
                    f'        [this](const QByteArray& j, DoneFn d) {{\n'
                    f'            invokeRpc<{inT}, {outT}>(this, j, d,\n'
                    f'                [this](grpc::ClientContext* ctx, const {inT}& r, {outT}* resp) {{\n'
                    f'                    auto stub = {class_}::NewStub(m_channel);\n'
                    f'                    return stub->{m.name}(ctx, r, resp);\n'
                    f'                }});\n'
                    f'        }});')
    dispatch_body = "\n\n".join(dispatch_blocks)

    return f'''#include "MainWindow.h"
#include "ui_MainWindow.h"

#include <QtConcurrent/QtConcurrentRun>
#include <QFutureWatcher>
#include <QCheckBox>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLineEdit>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStringList>
#include <QTextEdit>
#include <QUrl>

#include <grpcpp/grpcpp.h>
#include <google/protobuf/util/json_util.h>

#include <chrono>
#include <utility>

namespace {{

QString messageToJson(const google::protobuf::Message& msg) {{
    std::string out;
    google::protobuf::util::JsonPrintOptions opts;
    opts.add_whitespace = true;
    opts.preserve_proto_field_names = true;
    auto status = google::protobuf::util::MessageToJsonString(msg, &out, opts);
    if (!status.ok())
        return QStringLiteral("{{ \\"error\\": \\"%1\\" }}").arg(QString::fromStdString(std::string(status.message())));
    return QString::fromStdString(out);
}}

bool jsonToMessage(const QByteArray& json, google::protobuf::Message* msg, QString* err) {{
    auto status = google::protobuf::util::JsonStringToMessage(
        std::string(json.constData(), json.size()), msg);
    if (!status.ok()) {{
        if (err) *err = QString::fromStdString(std::string(status.message()));
        return false;
    }}
    return true;
}}

// invokeRpc: parse JSON -> typed Req, run sync RPC on worker, marshal
// typed Resp back to JSON.  CallFn signature:
//     grpc::Status (*)(grpc::ClientContext*, const Req&, Resp*)
template <class Req, class Resp, class CallFn>
void invokeRpcImpl(QObject* parent,
                   const QByteArray& body,
                   std::function<void(bool, const QString&)> done,
                   CallFn call) {{
    Req req;
    QString perr;
    if (!body.trimmed().isEmpty() && !jsonToMessage(body, &req, &perr)) {{
        done(false, QStringLiteral("JSON parse error: %1").arg(perr));
        return;
    }}
    auto* watcher = new QFutureWatcher<QString>(parent);
    QObject::connect(watcher, &QFutureWatcher<QString>::finished, parent,
        [watcher, done]() {{
            done(true, watcher->result());
            watcher->deleteLater();
        }});
    watcher->setFuture(QtConcurrent::run([req, call]() -> QString {{
        Resp resp;
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(10));
        auto status = call(&ctx, req, &resp);
        if (!status.ok())
            return QStringLiteral("RPC failed [%1] %2")
                .arg(status.error_code())
                .arg(QString::fromStdString(status.error_message()));
        return messageToJson(resp);
    }}));
}}

}}  // namespace

// Member helper redirects to the namespace-scoped template (template
// methods can't be defined out-of-class without the class declaration
// being a template, so we forward via a lambda capture).
template <class Req, class Resp, class CallFn>
static void invokeRpc(QObject* parent, const QByteArray& body,
                      std::function<void(bool, const QString&)> done, CallFn call) {{
    invokeRpcImpl<Req, Resp>(parent, body, done, call);
}}

MainWindow::MainWindow(QWidget* parent)
    : QWidget(parent), ui(new Ui::MainWindow), m_net(new QNetworkAccessManager(this)) {{
    ui->setupUi(this);

    setupDispatch();

    for (const auto& s : m_serviceList) ui->serviceCombo->addItem(s);
    onServiceChanged(0);

    if (!m_serviceList.isEmpty())
        ui->serviceNameEdit->setText(m_serviceList.first().toLower().replace(' ', '_'));

    connect(ui->connectButton, &QPushButton::clicked, this, &MainWindow::onConnectClicked);
    connect(ui->sendButton,    &QPushButton::clicked, this, &MainWindow::onSendClicked);
    connect(ui->serviceCombo,  QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWindow::onServiceChanged);
    connect(ui->useConsul,     &QCheckBox::toggled, this, &MainWindow::onUseConsulToggled);
    onUseConsulToggled(ui->useConsul->isChecked());
}}

MainWindow::~MainWindow() = default;

void MainWindow::onServiceChanged(int) {{
    ui->methodCombo->clear();
    for (const auto& m : m_methodsByService.value(ui->serviceCombo->currentText()))
        ui->methodCombo->addItem(m);
}}

void MainWindow::onUseConsulToggled(bool checked) {{
    ui->consulUrlEdit->setEnabled(checked);
    ui->serviceNameEdit->setEnabled(checked);
    ui->hostEdit->setEnabled(!checked);
}}

void MainWindow::onConnectClicked() {{
    if (ui->useConsul->isChecked()) {{
        resolveViaConsul();
    }} else {{
        // Strip http:// prefix if present - grpc::CreateChannel wants host:port.
        QString hp = ui->hostEdit->text().trimmed();
        if (hp.startsWith("http://"))  hp = hp.mid(7);
        if (hp.startsWith("https://")) hp = hp.mid(8);
        applyChannelHostPort(hp);
    }}
}}

void MainWindow::resolveViaConsul() {{
    const QString consul = ui->consulUrlEdit->text().trimmed();
    const QString svc    = ui->serviceNameEdit->text().trimmed();
    if (consul.isEmpty() || svc.isEmpty()) {{
        ui->statusLabel->setText("Consul URL and service name are required.");
        return;
    }}
    QUrl url(consul + "/v1/health/service/" + svc + "?passing=true");
    ui->statusLabel->setText(QStringLiteral("Resolving %1 via Consul...").arg(svc));

    auto* reply = m_net->get(QNetworkRequest(url));
    connect(reply, &QNetworkReply::finished, this, [this, reply, svc]() {{
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {{
            ui->statusLabel->setText(QStringLiteral("Consul error: %1").arg(reply->errorString()));
            return;
        }}
        const auto doc = QJsonDocument::fromJson(reply->readAll());
        if (!doc.isArray() || doc.array().isEmpty()) {{
            ui->statusLabel->setText(QStringLiteral("No healthy '%1'").arg(svc));
            return;
        }}
        const auto entry   = doc.array().first().toObject();
        const auto service = entry.value("Service").toObject();
        QString addr = service.value("Address").toString();
        if (addr.isEmpty())
            addr = entry.value("Node").toObject().value("Address").toString();
        const int port = service.value("Port").toInt();
        if (addr.isEmpty() || port <= 0) {{
            ui->statusLabel->setText("Consul entry missing Address/Port.");
            return;
        }}
        const QString hp = QStringLiteral("%1:%2").arg(addr).arg(port);
        ui->hostEdit->setText(hp);
        applyChannelHostPort(hp);
    }});
}}

void MainWindow::applyChannelHostPort(const QString& hostport) {{
    m_channel = grpc::CreateChannel(hostport.toStdString(),
                                    grpc::InsecureChannelCredentials());
    ui->statusLabel->setText(QStringLiteral("channel ready: %1 (lazy connect)").arg(hostport));
}}

void MainWindow::onSendClicked() {{
    if (!m_channel) {{
        ui->statusLabel->setText("Click Connect first.");
        return;
    }}
    const QString svc = ui->serviceCombo->currentText();
    const QString rpc = ui->methodCombo->currentText();
    const QString key = svc + QChar('.') + rpc;
    const QByteArray body = ui->requestEdit->toPlainText().toUtf8();

    auto it = m_dispatch.find(key);
    if (it == m_dispatch.end()) {{
        ui->statusLabel->setText(QStringLiteral("No dispatcher for %1").arg(key));
        return;
    }}

    ui->statusLabel->setText(QStringLiteral("Calling %1 ...").arg(key));
    ui->responseEdit->clear();
    it.value()(body, [this](bool ok, const QString& result) {{
        ui->responseEdit->setPlainText(result);
        ui->statusLabel->setText(ok ? "OK" : "FAILED");
    }});
}}

void MainWindow::setupDispatch() {{
{dispatch_body}
}}
'''


def _qt_client_grpcpp_build_qt_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
REM Build script for {spec.service_name} qt_client_grpcpp.  See README.md.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "PROJECT_ROOT=%SCRIPT_DIR%\\.."
set "BUILD_DIR=%SCRIPT_DIR%\\build"

if not defined VCPKG_ROOT (
    echo [build_qt] ERROR: VCPKG_ROOT not set.  setx VCPKG_ROOT C:\\vcpkg
    exit /b 1
)
if not defined QT_DIR (
    echo [build_qt] ERROR: QT_DIR not set.  setx QT_DIR C:\\Qt\\6.11.0\\mingw_64
    exit /b 1
)
if not defined QT_MINGW_BIN set "QT_MINGW_BIN=C:\\Qt\\Tools\\mingw1310_64\\bin"
if not exist "%QT_MINGW_BIN%\\g++.exe" (
    echo [build_qt] ERROR: Qt MinGW not found at %QT_MINGW_BIN%
    exit /b 1
)

REM One-time: copy upstream grpc port + apply our gcc 13 ICE patch.
if not exist "%PROJECT_ROOT%\\ports\\grpc\\portfile.cmake" (
    call "%PROJECT_ROOT%\\init_vcpkg_overlay.bat"
    if errorlevel 1 exit /b 1
)

set "PATH=%QT_MINGW_BIN%;%PATH%"
if exist "C:\\Qt\\Tools\\CMake_64\\bin\\cmake.exe" set "PATH=C:\\Qt\\Tools\\CMake_64\\bin;%PATH%"
if exist "C:\\Qt\\Tools\\Ninja\\ninja.exe"        set "PATH=C:\\Qt\\Tools\\Ninja;%PATH%"

REM Skip vcpkg install if USE_PREBUILT_VCPKG=1 and the install tree exists.
REM Goto-based control flow - chained `if A if B (...) else (...)` greedily
REM matches inner `if errorlevel 1 (..)` parens with the outer block, yielding
REM a stray `... was unexpected at this time` error.
if not "%USE_PREBUILT_VCPKG%"=="1" goto :do_vcpkg_install
if not exist "%BUILD_DIR%\\vcpkg_installed\\x64-mingw-qt\\share\\grpc" goto :do_vcpkg_install
echo [build_qt] USE_PREBUILT_VCPKG=1 + install tree present -^> skipping vcpkg install.
goto :after_vcpkg_install

:do_vcpkg_install
echo [build_qt] vcpkg install (slow on first run, instant after cache hit)...
"%VCPKG_ROOT%\\vcpkg.exe" install ^
    --x-manifest-root="%SCRIPT_DIR%" ^
    --x-install-root="%BUILD_DIR%\\vcpkg_installed" ^
    --overlay-triplets="%PROJECT_ROOT%\\triplets" ^
    --overlay-ports="%PROJECT_ROOT%\\ports" ^
    --triplet=x64-mingw-qt
if errorlevel 1 (
    echo [build_qt] vcpkg install failed.
    exit /b 1
)

:after_vcpkg_install

set "QT_MINGW_BIN_F=%QT_MINGW_BIN:\\=/%"
set "QT_DIR_F=%QT_DIR:\\=/%"
set "VCPKG_ROOT_F=%VCPKG_ROOT:\\=/%"
set "SCRIPT_DIR_F=%SCRIPT_DIR:\\=/%"
set "PROJECT_ROOT_F=%PROJECT_ROOT:\\=/%"

if exist "%BUILD_DIR%\\CMakeCache.txt" del /f /q "%BUILD_DIR%\\CMakeCache.txt"
if exist "%BUILD_DIR%\\CMakeFiles" rmdir /s /q "%BUILD_DIR%\\CMakeFiles"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

REM When USE_PREBUILT_VCPKG=1, also tell the vcpkg toolchain to skip
REM its auto-install step (otherwise it re-runs `vcpkg install` at
REM configure time and ignores our prebuilt tree).
set "MANIFEST_FLAG="
if "%USE_PREBUILT_VCPKG%"=="1" set "MANIFEST_FLAG=-DVCPKG_MANIFEST_INSTALL=OFF"

cmake -S "%SCRIPT_DIR_F%" -B "%BUILD_DIR%" -G Ninja ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT_F%/scripts/buildsystems/vcpkg.cmake" ^
    -DVCPKG_TARGET_TRIPLET=x64-mingw-qt ^
    -DVCPKG_OVERLAY_TRIPLETS="%PROJECT_ROOT_F%/triplets" ^
    -DVCPKG_OVERLAY_PORTS="%PROJECT_ROOT_F%/ports" ^
    -DCMAKE_PREFIX_PATH="%QT_DIR_F%" ^
    -DCMAKE_C_COMPILER="%QT_MINGW_BIN_F%/gcc.exe" ^
    -DCMAKE_CXX_COMPILER="%QT_MINGW_BIN_F%/g++.exe" ^
    %MANIFEST_FLAG%
if errorlevel 1 ( echo [build_qt] cmake configure failed. & exit /b 1 )

cmake --build "%BUILD_DIR%" --parallel
if errorlevel 1 ( echo [build_qt] cmake build failed. & exit /b 1 )

echo.
echo [build_qt] OK -^> %BUILD_DIR%\\{sn}_qt_gui.exe
endlocal
'''


def _qt_client_grpcpp_deploy_qt_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
REM Bundle .exe + Qt DLLs + vcpkg DLLs + MinGW runtime into deploy\\.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\\build"
set "DEPLOY_DIR=%SCRIPT_DIR%\\deploy"
set "EXE_NAME={sn}_qt_gui.exe"

if not exist "%BUILD_DIR%\\%EXE_NAME%" (
    echo [deploy] ERROR: %BUILD_DIR%\\%EXE_NAME% not found.  Run build_qt.bat first.
    exit /b 1
)
if not defined QT_DIR set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"
REM windeployqt presence is checked later via the multi-name fallback loop;
REM Qt 6.5-6.7 ship windeployqt-qt6.exe, 6.8+ ship windeployqt6.exe, and
REM the generic windeployqt.exe is in every variant.

if exist "%DEPLOY_DIR%" rmdir /s /q "%DEPLOY_DIR%"
mkdir "%DEPLOY_DIR%"

echo [deploy] Copying %EXE_NAME%
copy /y "%BUILD_DIR%\\%EXE_NAME%" "%DEPLOY_DIR%\\" >nul

REM windeployqt name varies by Qt version: windeployqt-qt6 (6.5-6.7),
REM windeployqt6 (6.8+), or generic windeployqt.exe.
set "WINDEPLOYQT="
for %%E in (windeployqt-qt6.exe windeployqt6.exe windeployqt.exe) do (
    if not defined WINDEPLOYQT if exist "%QT_DIR%\\bin\\%%E" set "WINDEPLOYQT=%QT_DIR%\\bin\\%%E"
)
if not defined WINDEPLOYQT (
    echo [deploy] ERROR: no windeployqt found in %QT_DIR%\\bin.  GUI exe will fail at runtime.
    exit /b 1
)
echo [deploy] windeployqt - %WINDEPLOYQT% - auto-detect Qt DLLs from exe PE header
"%WINDEPLOYQT%" --no-translations --no-system-d3d-compiler --no-opengl-sw "%DEPLOY_DIR%\\%EXE_NAME%"
if errorlevel 1 ( echo [deploy] windeployqt failed. & exit /b 1 )

set "VCPKG_BIN=%BUILD_DIR%\\vcpkg_installed\\x64-mingw-qt\\bin"
echo [deploy] Copying vcpkg runtime DLLs
for %%F in (libabseil_dll.dll libcares.dll libcrypto-3-x64.dll libprotobuf.dll libprotobuf-lite.dll libre2.dll libssl-3-x64.dll libzlib1.dll legacy.dll) do (
    if exist "%VCPKG_BIN%\\%%F" copy /y "%VCPKG_BIN%\\%%F" "%DEPLOY_DIR%\\" >nul
)

echo.
echo [deploy] Bundle ready at %DEPLOY_DIR%
dir /b "%DEPLOY_DIR%"
endlocal
'''


def _qt_client_grpcpp_export_prebuilt_bat(spec) -> str:
    return '''@echo off
REM Package vcpkg artifacts so other devs build without rebuilding grpc/protobuf.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\\build"
set "INSTALLED_PARENT=%BUILD_DIR%\\vcpkg_installed"
set "INSTALLED=%INSTALLED_PARENT%\\x64-mingw-qt"
set "OUT_DIR=%SCRIPT_DIR%\\prebuilt"

if not exist "%INSTALLED%" (
    echo [export] ERROR: %INSTALLED% not found.  Run build_qt.bat first.
    exit /b 1
)
set "TAR_EXE=%SystemRoot%\\System32\\tar.exe"
if not exist "%TAR_EXE%" (
    echo [export] ERROR: %TAR_EXE% not found.  Need Windows 10 1803+.
    exit /b 1
)

if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%"

REM Pack x64-mingw-qt + only x64-windows/tools/grpc/ (host grpc_cpp_plugin).
REM Skip x64-windows/tools/protobuf/ - protoc.exe is also at
REM x64-mingw-qt/tools/protobuf/ and CMakeLists pre-sets Protobuf_PROTOC_EXECUTABLE
REM there before find_package, so we don't need x64-windows for protoc.
set "PACK_ARGS=x64-mingw-qt"
if exist "%INSTALLED_PARENT%\\x64-windows\\tools\\grpc" (
    set "PACK_ARGS=%PACK_ARGS% x64-windows\\tools\\grpc"
    echo [export] Including x64-windows\\tools\\grpc - host grpc_cpp_plugin.
)
echo [export] Packing installed tree
"%TAR_EXE%" -a -cf "%OUT_DIR%\\vcpkg_installed_x64-mingw-qt.zip" -C "%INSTALLED_PARENT%" %PACK_ARGS%
if errorlevel 1 ( echo [export] tar failed. & exit /b 1 )

set "CACHE_PARENT=%LOCALAPPDATA%\\vcpkg"
if exist "%CACHE_PARENT%\\archives" (
    echo [export] Packing vcpkg binary cache
    "%TAR_EXE%" -a -cf "%OUT_DIR%\\vcpkg_binary_cache.zip" -C "%CACHE_PARENT%" "archives"
)

echo.
echo [export] Done.
dir /b "%OUT_DIR%"
echo.
echo [export] Receiving PC:
echo   Method A: unzip vcpkg_installed_x64-mingw-qt.zip into qt_client_grpcpp\\build\\vcpkg_installed\\
echo   Method B: unzip vcpkg_binary_cache.zip into %%LOCALAPPDATA%%\\vcpkg\\
echo   Then run build_qt.bat as usual.
endlocal
'''


def _client_deploy_qt_vcpkg_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
REM Bundle the {spec.service_name} console + Qt GUI client (built via vcpkg
REM + Qt MinGW) into client\\dist-qt-vcpkg\\.  Self-contained.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "DIST=%SCRIPT_DIR%\\dist-qt-vcpkg"

if not defined QT_MINGW_BIN set "QT_MINGW_BIN=C:\\Qt\\Tools\\mingw1310_64\\bin"
if not defined QT_DIR       set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"

set "BUILD_DIR="
if exist "%SCRIPT_DIR%\\build-qt-vcpkg\\{sn}_client.exe" (
    set "BUILD_DIR=%SCRIPT_DIR%\\build-qt-vcpkg"
    set "BUILD_LABEL=CLI build-qt-vcpkg"
)
if not defined BUILD_DIR (
    for /d %%D in ("%SCRIPT_DIR%\\build\\Desktop_Qt_*") do (
        if exist "%%D\\{sn}_client.exe" (
            if not defined BUILD_DIR (
                set "BUILD_DIR=%%D"
                set "BUILD_LABEL=Qt Creator [%%~nxD]"
            )
        )
    )
)
if not defined BUILD_DIR (
    echo [deploy] ERROR: no {sn}_client.exe found in any build dir.
    exit /b 1
)
set "VCPKG_BIN=%BUILD_DIR%\\vcpkg_installed\\x64-mingw-qt\\bin"
if not exist "%VCPKG_BIN%" ( echo [deploy] ERROR: %VCPKG_BIN% missing. & exit /b 1 )
if not exist "%QT_MINGW_BIN%\\g++.exe" ( echo [deploy] ERROR: Qt MinGW not at %QT_MINGW_BIN%. & exit /b 1 )

echo [deploy] Build dir : %BUILD_DIR%
echo [deploy] Source    : !BUILD_LABEL!

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

echo [deploy] Copying client executables
for %%F in ("%BUILD_DIR%\\*.exe") do (
    copy /y "%%F" "%DIST%\\" >nul
    echo   - %%~nxF
)

echo [deploy] Copying vcpkg runtime DLLs from %VCPKG_BIN%
for %%F in (libabseil_dll.dll libcares.dll libcrypto-3-x64.dll libprotobuf.dll libprotobuf-lite.dll libre2.dll libssl-3-x64.dll libzlib1.dll legacy.dll libcurl.dll) do (
    if exist "%VCPKG_BIN%\\%%F" copy /y "%VCPKG_BIN%\\%%F" "%DIST%\\" >nul && echo   - %%F
)
for %%F in ("%VCPKG_BIN%\\*.dll") do (
    if not exist "%DIST%\\%%~nxF" (
        copy /y "%%F" "%DIST%\\" >nul
        echo   - %%~nxF [extra]
    )
)

echo [deploy] Copying MinGW runtime DLLs from %QT_MINGW_BIN%
for %%F in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll) do (
    if exist "%QT_MINGW_BIN%\\%%F" copy /y "%QT_MINGW_BIN%\\%%F" "%DIST%\\" >nul && echo   - %%F
)

REM windeployqt: try multiple names (Qt 6.5-6.7: windeployqt-qt6, 6.8+: windeployqt6, generic: windeployqt).
set "WINDEPLOYQT="
for %%E in (windeployqt-qt6.exe windeployqt6.exe windeployqt.exe) do (
    if not defined WINDEPLOYQT if exist "%QT_DIR%\\bin\\%%E" set "WINDEPLOYQT=%QT_DIR%\\bin\\%%E"
)
if exist "%DIST%\\{sn}_gui.exe" (
    if defined WINDEPLOYQT (
        echo [deploy] Running !WINDEPLOYQT! for {sn}_gui.exe
        REM Auto-detect Debug/Release from PE header.  --compiler-runtime is MSVC-only.
        "!WINDEPLOYQT!" --no-translations ^
            --no-system-d3d-compiler --no-opengl-sw ^
            "%DIST%\\{sn}_gui.exe"
    ) else (
        echo [deploy] WARN: no windeployqt at %QT_DIR%\\bin - GUI will fail without Qt DLLs.
    )
)

echo [deploy] Emitting run_*.bat launchers
for %%F in ("%DIST%\\*.exe") do (
    call :emit_launcher "%DIST%\\run_%%~nF.bat" "%%~nxF"
)

echo;
echo [deploy] Bundle ready at %DIST%
echo [deploy] Run console:  %DIST%\\run_{sn}_client.bat
echo [deploy] Run GUI:      %DIST%\\run_{sn}_gui.bat
goto :eof

:emit_launcher
> "%~1" echo @echo off
>> "%~1" echo "%%~dp0%~2" %%*
exit /b 0
'''


def _server_deploy_qt_vcpkg_bat(spec) -> str:
    return '''@echo off
REM Bundle server (and optional Qt client) built via vcpkg + Qt MinGW
REM into dist-qt-vcpkg\\.  Self-contained: zip + copy to any Win x64 PC,
REM no Qt/vcpkg/MinGW install needed on target.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\\build-qt-vcpkg"
set "DIST=%SCRIPT_DIR%\\dist-qt-vcpkg"
set "VCPKG_BIN=%BUILD_DIR%\\vcpkg_installed\\x64-mingw-qt\\bin"
set "CLIENT_BUILD=%SCRIPT_DIR%\\qt_client_grpcpp\\build"

if not defined QT_MINGW_BIN set "QT_MINGW_BIN=C:\\Qt\\Tools\\mingw1310_64\\bin"
if not defined QT_DIR       set "QT_DIR=C:\\Qt\\6.11.0\\mingw_64"

if not exist "%BUILD_DIR%" ( echo [deploy] ERROR: %BUILD_DIR% not found - run build_qt_vcpkg.bat. & exit /b 1 )
if not exist "%VCPKG_BIN%" ( echo [deploy] ERROR: %VCPKG_BIN% not found. & exit /b 1 )
if not exist "%QT_MINGW_BIN%\\g++.exe" ( echo [deploy] ERROR: Qt MinGW not at %QT_MINGW_BIN%. & exit /b 1 )

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

echo [deploy] Copying server executables from %BUILD_DIR%
for %%F in ("%BUILD_DIR%\\*.exe") do (
    copy /y "%%F" "%DIST%\\" >nul
    echo   - %%~nxF
)

set "HAVE_CLIENT=0"
if exist "%CLIENT_BUILD%" (
    for %%F in ("%CLIENT_BUILD%\\*.exe") do (
        if not "!HAVE_CLIENT!"=="1" echo [deploy] Copying Qt client from %CLIENT_BUILD%
        copy /y "%%F" "%DIST%\\" >nul
        echo   - %%~nxF
        set "HAVE_CLIENT=1"
    )
)
if "!HAVE_CLIENT!"=="0" echo [deploy] No Qt client built - server-only deploy.

echo [deploy] Copying vcpkg runtime DLLs from %VCPKG_BIN%
for %%F in (libabseil_dll.dll libcares.dll libcrypto-3-x64.dll libprotobuf.dll libprotobuf-lite.dll libre2.dll libssl-3-x64.dll libzlib1.dll legacy.dll libcurl.dll) do (
    if exist "%VCPKG_BIN%\\%%F" copy /y "%VCPKG_BIN%\\%%F" "%DIST%\\" >nul && echo   - %%F
)
REM Pull in any other DLLs vcpkg dropped (transitive deps).  Avoid `(extra)`
REM literal parens - they conflict with for-body block delimiters in cmd.
for %%F in ("%VCPKG_BIN%\\*.dll") do (
    if not exist "%DIST%\\%%~nxF" (
        copy /y "%%F" "%DIST%\\" >nul
        echo   - %%~nxF [extra]
    )
)

echo [deploy] Copying MinGW runtime DLLs from %QT_MINGW_BIN%
for %%F in (libstdc++-6.dll libgcc_s_seh-1.dll libwinpthread-1.dll) do (
    if exist "%QT_MINGW_BIN%\\%%F" copy /y "%QT_MINGW_BIN%\\%%F" "%DIST%\\" >nul && echo   - %%F
)

set "WINDEPLOYQT="
for %%E in (windeployqt-qt6.exe windeployqt6.exe windeployqt.exe) do (
    if not defined WINDEPLOYQT if exist "%QT_DIR%\\bin\\%%E" set "WINDEPLOYQT=%QT_DIR%\\bin\\%%E"
)
if "!HAVE_CLIENT!"=="1" if defined WINDEPLOYQT (
    echo [deploy] Running !WINDEPLOYQT! for Qt client
    for %%F in ("%CLIENT_BUILD%\\*.exe") do (
        "!WINDEPLOYQT!" --no-translations ^
            --no-system-d3d-compiler --no-opengl-sw ^
            "%DIST%\\%%~nxF"
    )
)

REM run_<svc>.bat launchers - one-line, %~dp0 resolves at launch time so
REM Windows DLL search starts in dist\\ where all our deps live.  Avoid
REM %% / %DIST% / %PATH% reuse (parent script has them set, would expand).
echo [deploy] Emitting run_*.bat launchers
for %%F in ("%DIST%\\*.exe") do (
    call :emit_launcher "%DIST%\\run_%%~nF.bat" "%%~nxF"
)

REM Re-point Nomad HCL files (deploy/*.nomad.hcl) into dist-qt-vcpkg/.
if exist "%SCRIPT_DIR%\\deploy\\*.nomad.hcl" (
    REM Step 1: ensure source HCLs have the project's actual path baked in.
    REM prep_nomad_paths.bat rewrites C:/path/to/<project> placeholders to
    REM the real %SCRIPT_DIR% (idempotent -- skips files already rewritten).
    if exist "%SCRIPT_DIR%\\prep_nomad_paths.bat" (
        echo [deploy] Resolving Nomad HCL placeholders ^(prep_nomad_paths.bat^)
        call "%SCRIPT_DIR%\\prep_nomad_paths.bat" >nul
    )
    echo [deploy] Re-pointing Nomad HCL files to %DIST%
    if not exist "%DIST%\\deploy" mkdir "%DIST%\\deploy"
    set "DIST_FWD=%DIST:\\=/%"
    for %%H in ("%SCRIPT_DIR%\\deploy\\*.nomad.hcl") do call :rewrite_hcl "%%H"
)

echo.
echo [deploy] Bundle ready at %DIST%
echo [deploy] Run a service:  %DIST%\\run_^<service^>.bat
echo [deploy] Or via Nomad:    nomad job run %DIST%\\deploy\\^<service^>.nomad.hcl
goto :eof

:emit_launcher
> "%~1" echo @echo off
>> "%~1" echo "%%~dp0%~2" %%*
exit /b 0

:rewrite_hcl
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-Content -Raw -LiteralPath '%~1'; $c = $c -replace 'C:/path/to/[^/]+/dist-msys2', '%DIST_FWD%'; $c = $c -replace 'dist-msys2', 'dist-qt-vcpkg'; Set-Content -LiteralPath '%DIST%\\deploy\\%~nx1' -NoNewline -Value $c"
echo   - deploy\\%~nx1
goto :eof
'''


def _server_build_qt_vcpkg_bat(spec) -> str:
    sn = spec.snake_name
    return f'''@echo off
REM Build {spec.service_name} server using vcpkg + Qt MinGW (matches the
REM qt_client_grpcpp/ toolchain so client + server share one compiler ABI).
REM
REM To skip the vcpkg build entirely (use prebuilt artifacts shared by
REM another developer), set USE_PREBUILT_VCPKG=1 and unzip the prebuilt
REM tree into %BUILD_DIR%\\vcpkg_installed\\x64-mingw-qt\\ first.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BUILD_DIR=%SCRIPT_DIR%\\build-qt-vcpkg"

if not defined VCPKG_ROOT ( echo [build] ERROR: VCPKG_ROOT not set. & exit /b 1 )
if not defined QT_MINGW_BIN set "QT_MINGW_BIN=C:\\Qt\\Tools\\mingw1310_64\\bin"
if not exist "%QT_MINGW_BIN%\\g++.exe" (
    echo [build] ERROR: Qt MinGW not found at %QT_MINGW_BIN%
    exit /b 1
)

if not exist "%SCRIPT_DIR%\\ports\\grpc\\portfile.cmake" (
    call "%SCRIPT_DIR%\\init_vcpkg_overlay.bat"
    if errorlevel 1 exit /b 1
)

set "PATH=%QT_MINGW_BIN%;%PATH%"
if exist "C:\\Qt\\Tools\\CMake_64\\bin\\cmake.exe" set "PATH=C:\\Qt\\Tools\\CMake_64\\bin;%PATH%"
if exist "C:\\Qt\\Tools\\Ninja\\ninja.exe"        set "PATH=C:\\Qt\\Tools\\Ninja;%PATH%"

REM ---- vcpkg install ------------------------------------------------------
REM Goto-based control flow - chained `if A if B (...) else (...)` greedily
REM matches inner `if errorlevel 1 (..)` parens with the outer block.
if not "%USE_PREBUILT_VCPKG%"=="1" goto :do_vcpkg_install
if not exist "%BUILD_DIR%\\vcpkg_installed\\x64-mingw-qt\\share\\grpc" goto :do_vcpkg_install
echo [build] USE_PREBUILT_VCPKG=1 + install tree present -^> skipping vcpkg install.
goto :after_vcpkg_install

:do_vcpkg_install
echo [build] vcpkg install (slow on first run, instant after cache hit)...
"%VCPKG_ROOT%\\vcpkg.exe" install ^
    --x-manifest-root="%SCRIPT_DIR%" ^
    --x-install-root="%BUILD_DIR%\\vcpkg_installed" ^
    --overlay-triplets="%SCRIPT_DIR%\\triplets" ^
    --overlay-ports="%SCRIPT_DIR%\\ports" ^
    --triplet=x64-mingw-qt
if errorlevel 1 (
    echo [build] vcpkg install failed.
    exit /b 1
)

:after_vcpkg_install

set "QT_MINGW_BIN_F=%QT_MINGW_BIN:\\=/%"
set "VCPKG_ROOT_F=%VCPKG_ROOT:\\=/%"
set "SCRIPT_DIR_F=%SCRIPT_DIR:\\=/%"

if exist "%BUILD_DIR%\\CMakeCache.txt" del /f /q "%BUILD_DIR%\\CMakeCache.txt"
if exist "%BUILD_DIR%\\CMakeFiles" rmdir /s /q "%BUILD_DIR%\\CMakeFiles"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

set "MANIFEST_FLAG="
if "%USE_PREBUILT_VCPKG%"=="1" set "MANIFEST_FLAG=-DVCPKG_MANIFEST_INSTALL=OFF"

cmake -S "%SCRIPT_DIR_F%" -B "%BUILD_DIR%" -G Ninja ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_TOOLCHAIN_FILE="%VCPKG_ROOT_F%/scripts/buildsystems/vcpkg.cmake" ^
    -DVCPKG_TARGET_TRIPLET=x64-mingw-qt ^
    -DVCPKG_OVERLAY_TRIPLETS="%SCRIPT_DIR_F%/triplets" ^
    -DVCPKG_OVERLAY_PORTS="%SCRIPT_DIR_F%/ports" ^
    -DCMAKE_C_COMPILER="%QT_MINGW_BIN_F%/gcc.exe" ^
    -DCMAKE_CXX_COMPILER="%QT_MINGW_BIN_F%/g++.exe" ^
    %MANIFEST_FLAG%
if errorlevel 1 ( echo [build] cmake configure failed. & exit /b 1 )

cmake --build "%BUILD_DIR%" --parallel
if errorlevel 1 ( echo [build] cmake build failed. & exit /b 1 )

echo.
echo [build] OK.  Built executables in %BUILD_DIR%:
dir /b "%BUILD_DIR%\\*.exe" 2>nul
endlocal
'''


def _qt_client_grpcpp_readme(spec) -> str:
    sn = spec.snake_name
    return f'''# {spec.service_name} Qt Client (Google grpc++ via vcpkg)

Qt Widgets UI client for **{spec.service_name}** that links Google's
`grpc++` C++ library (built by vcpkg with the **Qt-installer MinGW
13.1.0** toolchain).  Companion to the server in the parent project,
which can also be built with the same toolchain via `..\\build_qt_vcpkg.bat`.

## Why this variant

Sibling `qt_client/` (when picked) uses **Qt6::Grpc + Qt6::Protobuf** —
Qt-native, no Google grpc dependency on the client side.  This variant
(`qt_client_grpcpp/`) uses **Google grpc++** end-to-end so client and
server share one transport library.  Tradeoff: ~30–60 min first-time
vcpkg build.

## Prerequisites (one-time)

1. Qt 6.x installed via Online Installer, including **MinGW 13.1.0 64-bit** under Tools.
2. vcpkg cloned + bootstrapped:
   ```bat
   git clone https://github.com/microsoft/vcpkg.git C:\\vcpkg
   C:\\vcpkg\\bootstrap-vcpkg.bat
   setx VCPKG_ROOT C:\\vcpkg
   ```
3. Set Qt prefix:
   ```bat
   setx QT_DIR C:\\Qt\\6.11.0\\mingw_64
   ```
4. Optional: override Qt MinGW path: `setx QT_MINGW_BIN C:\\Qt\\Tools\\mingw1310_64\\bin`

## Build

```bat
build_qt.bat
```

First run: vcpkg compiles `boringssl + abseil + protobuf + grpc` with Qt
MinGW (~30–60 min wall time, mostly idle).  Subsequent runs hit the
binary cache and complete in seconds.

Output: `build\\{sn}_qt_gui.exe` linking against vcpkg DLLs in
`build\\vcpkg_installed\\x64-mingw-qt\\bin\\`.

## Deploy to another PC (no rebuild)

```bat
deploy_qt.bat
```

Bundles `.exe` + Qt DLLs + vcpkg DLLs + MinGW runtime into `deploy\\`.
Zip + copy to any Windows x64 PC; no Qt / vcpkg / MinGW install required
on target.

## Share build artifacts with other developers (skip vcpkg rebuild)

```bat
export_prebuilt.bat
```

Produces:

- `prebuilt\\vcpkg_installed_x64-mingw-qt.zip` (~50–80 MB)
- `prebuilt\\vcpkg_binary_cache.zip` (vcpkg cache zips)

Receiving PC: unzip the installed tree into `qt_client_grpcpp\\build\\vcpkg_installed\\`,
then `build_qt.bat` skips the install step entirely.

## Troubleshooting

- **`ninja: manifest 'build.ninja' still dirty after 100 tries`** — gcc
  13.1.0 ICE in grpc; the overlay-port at `..\\ports\\grpc\\` includes a
  workaround patch (`00018-gcc13-per-cpu-ice-workaround.patch`).
- **`protoc not found`** — vcpkg installs its own protoc; check
  `build\\vcpkg_installed\\x64-mingw-qt\\tools\\protobuf\\protoc.exe`.
- **`Failed to find required Qt component`** — set `QT_DIR` or
  `Qt6_DIR` env var pointing at `C:\\Qt\\6.x.y\\mingw_64`.
- **`cmake: Invalid character escape '\\Q'`** — old `CMakeFiles\\` from
  a previous failed configure; `build_qt.bat` wipes them on each run.

## Use with Qt Creator

Open `CMakeLists.txt` in Qt Creator.  In **Project → Build → CMake →
Initial Configuration**, add:

```
-DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake
-DVCPKG_TARGET_TRIPLET=x64-mingw-qt
-DVCPKG_OVERLAY_TRIPLETS=%{{sourceDir}}/../triplets
-DVCPKG_OVERLAY_PORTS=%{{sourceDir}}/../ports
```

Configure → vcpkg toolchain auto-installs deps (or restores from cache).
Drop `build/vcpkg_installed/x64-mingw-qt/` from a teammate's
`export_prebuilt.bat` to skip the install entirely.
'''
