"""C++ service scaffold templates.

Generates CMake-based projects for gRPC microservices using the
MicroserviceBase C++ runtime (ServiceRunner + ConsulRegistration).
Supports four GUI variants: none, qml, wasm, widget.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict

from ._template_loader import load_raw, load_template
from .shared import cpp_file_header

if TYPE_CHECKING:
    from .generator import ScaffoldSpec


# Reusable CMake function emitted into every top-level CMakeLists.txt.
# Loaded once from cpp/cmake/_mb_deploy_runtime.cmake.tmpl at module
# import time; reused across every CMakeLists template that needs it.
# Substitute with no kwargs returns the file verbatim.
_MB_DEPLOY_RUNTIME_BLOCK = load_template("cpp/cmake/_mb_deploy_runtime.cmake.tmpl")


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
    svc = spec.service_name
    grpc_name = _grpc_svc_name(spec)
    upper = _upper(svc)

    proto_block = load_template(
        "cpp/cmake/proto_stubs.cmake.tmpl",
        snake_name=sn,
        service_upper=upper,
    )
    exe_block = load_template(
        "cpp/cmake/server_exe.cmake.tmpl",
        snake_name=sn,
        service_name=svc,
        service_upper=upper,
        grpc_name=grpc_name,
    )
    return load_template(
        "cpp/cmake/CMakeLists.server.txt.tmpl",
        service_name=svc,
        version=spec.version,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
        proto_block=proto_block,
        exe_block=exe_block,
    )


def _main_cpp(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    grpc_name = _grpc_svc_name(spec)
    header = cpp_file_header(
        "main.cpp",
        f"Entry point for the {svc} service.\n"
        f"Composes Settings, the domain class, and the gRPC adapter, then\n"
        f"hands them to ServiceRunner which manages the gRPC server\n"
        f"lifecycle and Consul registration.",
    )
    return load_template(
        "cpp/server/main.cpp.tmpl",
        header=header,
        snake_name=spec.snake_name,
        proto_package=spec.proto_package,
        grpc_name=grpc_name,
        service_name=svc,
    )


# -----------------------------------------------------------------------
# src/Settings.h
# -----------------------------------------------------------------------

def _settings_h(spec: "ScaffoldSpec") -> str:
    prefix = spec.env_prefix
    header = cpp_file_header(
        "Settings.h",
        f"Service-specific settings for {spec.service_name}.\n"
        f"Loads all base fields (service_host, grpc_port, advertise_addr,\n"
        f"consul_addr, consul_token, log_level) from environment variables\n"
        f"prefixed with `{prefix}`.  Add service-specific fields below by\n"
        f"declaring members and calling readEnv() inside the constructor.",
    )
    return load_template(
        "cpp/server/Settings.h.tmpl",
        header=header,
        snake_name=spec.snake_name,
        service_name=spec.service_name,
        env_prefix=prefix,
    )


# -----------------------------------------------------------------------
# Domain
# -----------------------------------------------------------------------

def _domain_h(spec: "ScaffoldSpec") -> str:
    grpc_name = _grpc_svc_name(spec)
    imported = any(m.input_type or m.output_type for m in spec.methods)

    header = cpp_file_header(
        f"{grpc_name}.h",
        f"Domain class for the {spec.service_name} service.\n"
        f"Pure business logic - no gRPC, no I/O, no protobuf types.\n"
        f"All inbound traffic enters through the gRPC adapter and is\n"
        f"translated into method calls on this class.",
    )

    if imported:
        return load_template(
            "cpp/server/domain.h.imported.tmpl",
            header=header,
            snake_name=spec.snake_name,
            service_name=spec.service_name,
            grpc_name=grpc_name,
        )

    methods_parts = []
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        param_doc = "\n".join(
            f"     * @param {p.name} TODO: describe ``{p.name}``."
            for p in m.params
        )
        param_doc_block = f"     *\n{param_doc}\n" if param_doc else ""
        methods_parts.append(load_template(
            "cpp/server/domain.h.method.tmpl",
            method_name=m.name,
            snake_method=_snake(m.name),
            params=params,
            param_doc_block=param_doc_block,
        ))
    methods = "".join(methods_parts) if methods_parts else "    // Add methods here."

    return load_template(
        "cpp/server/domain.h.tmpl",
        header=header,
        snake_name=spec.snake_name,
        service_name=spec.service_name,
        grpc_name=grpc_name,
        methods=methods,
    )


def _domain_cpp(spec: "ScaffoldSpec") -> str:
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
        return load_template(
            "cpp/server/domain.cpp.imported.tmpl",
            header=header,
            snake_name=spec.snake_name,
            grpc_name=grpc_name,
        )

    methods_parts = []
    for m in spec.methods:
        params = ", ".join(f"const std::string& {p.name}" for p in m.params)
        methods_parts.append(load_template(
            "cpp/server/domain.cpp.method.tmpl",
            method_name=m.name,
            snake_method=_snake(m.name),
            grpc_name=grpc_name,
            params=params,
        ))
    methods = "".join(methods_parts) if methods_parts else "// Add implementations here."

    return load_template(
        "cpp/server/domain.cpp.tmpl",
        header=header,
        snake_name=spec.snake_name,
        grpc_name=grpc_name,
        methods=methods,
    )

# -----------------------------------------------------------------------
# gRPC Adapter
# -----------------------------------------------------------------------

def _adapter_h(spec: "ScaffoldSpec") -> str:
    ns = spec.proto_namespace
    svc = spec.service_name
    grpc_name = _grpc_svc_name(spec)

    methods_parts = []
    for m in spec.methods:
        inT  = ("::" + m.input_type.replace(".", "::")) if m.input_type else f"{ns}::{m.name}Request"
        outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"
        tmpl = ("cpp/server/adapter.h.method_streaming.tmpl"
                if m.server_streaming
                else "cpp/server/adapter.h.method_unary.tmpl")
        methods_parts.append(load_template(
            tmpl, method_name=m.name, input_type=inT, output_type=outT))
    methods = "".join(methods_parts)

    header = cpp_file_header(
        f"{svc}GrpcAdapter.h",
        f"gRPC inbound adapter for {grpc_name}.\n"
        f"Translates protobuf request/response messages into method calls\n"
        f"on the {grpc_name} domain class.  One method per RPC, generated\n"
        f"from the .proto file.  Do not change the signatures (they are\n"
        f"required by the proto-generated servicer base class); edit only\n"
        f"the bodies in {svc}GrpcAdapter.cpp to plug in real logic.",
    )
    return load_template(
        "cpp/server/adapter.h.tmpl",
        header=header,
        snake_name=spec.snake_name,
        service_name=svc,
        grpc_name=grpc_name,
        proto_namespace=ns,
        methods=methods,
    )


def _adapter_cpp(spec: "ScaffoldSpec") -> str:
    ns = spec.proto_namespace
    svc = spec.service_name

    methods_parts = []
    for m in spec.methods:
        imported = bool(m.input_type or m.output_type)
        inT  = ("::" + m.input_type.replace(".", "::")) if m.input_type else f"{ns}::{m.name}Request"
        outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"

        if imported:
            tmpl = ("cpp/server/adapter.cpp.method_streaming_imported.tmpl"
                    if m.server_streaming
                    else "cpp/server/adapter.cpp.method_unary_imported.tmpl")
            methods_parts.append(load_template(
                tmpl, service_name=svc, method_name=m.name,
                input_type=inT, output_type=outT))
            continue

        param_reads = "\n".join(
            f"    auto _{p.name} = request->{p.name}();" for p in m.params
        )
        args = ", ".join(f"_{p.name}" for p in m.params)
        tmpl = ("cpp/server/adapter.cpp.method_streaming.tmpl"
                if m.server_streaming
                else "cpp/server/adapter.cpp.method_unary.tmpl")
        methods_parts.append(load_template(
            tmpl,
            service_name=svc,
            method_name=m.name,
            snake_method=_snake(m.name),
            input_type=inT,
            output_type=outT,
            param_reads=param_reads,
            args=args,
        ))
    methods = "".join(methods_parts)

    header = cpp_file_header(
        f"{svc}GrpcAdapter.cpp",
        f"Implementations for {svc}GrpcAdapter.\n"
        f"Each method unpacks the proto request, calls into the domain\n"
        f"object via m_domain, and packs the result into the response\n"
        f"message.  Imported-proto methods emit UNIMPLEMENTED until the\n"
        f"author wires them up - the service still builds and starts.",
    )
    return load_template(
        "cpp/server/adapter.cpp.tmpl",
        header=header,
        snake_name=spec.snake_name,
        service_name=svc,
        methods=methods,
    )


# -----------------------------------------------------------------------
# Central env var scripts (set_env.bat / set_env.sh)
#
# Every other script calls/sources this file, so the user only edits
# paths here.  Variables already defined in the shell/system are left
# alone — useful when running in CI or when the user prefers global
# System Environment Variables.
# -----------------------------------------------------------------------

def _set_env_bat(spec: "ScaffoldSpec") -> str:
    """MSVC flavor of set_env.bat - authoritative (no 'if not defined')."""
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

    return load_template(
        "cpp/build/set_env.bat.tmpl",
        qt_line=qt_line, qt_summary=qt_summary,
        wasm_block=wasm_block, wasm_summary=wasm_summary,
    )


def _set_env_mingw_bat(spec: "ScaffoldSpec") -> str:
    """MinGW flavor of set_env.bat - authoritative (no 'if not defined')."""
    qt_line = ""
    qt_summary = ""
    if spec.gui_type in ("widget", "wasm"):
        qt_line = 'set "QT_DIR=C:\\Qt\\6.7.1\\mingw_64"\n'
        qt_summary = 'echo   QT_DIR        = %QT_DIR%\n'

    return load_template(
        "cpp/build/set_env_mingw.bat.tmpl",
        qt_line=qt_line, qt_summary=qt_summary,
    )


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

    return load_template(
        "cpp/build/set_env.sh.tmpl",
        qt_line=qt_line, qt_summary=qt_summary,
        wasm_block=wasm_block, wasm_summary=wasm_summary,
    )


# -----------------------------------------------------------------------
# Build scripts
# -----------------------------------------------------------------------

def _build_bat(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    windeployqt_block = ""
    if spec.gui_type == "widget":
        windeployqt_block = load_template(
            "cpp/build/windeployqt.msvc.bat.tmpl", snake_name=sn)
    return load_template(
        "cpp/build/build_deploy.bat.tmpl",
        snake_name=sn,
        windeployqt_block=windeployqt_block,
    )


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
        windeployqt_block = load_template(
            "cpp/build/windeployqt.mingw.bat.tmpl", snake_name=sn)
    return load_template(
        "cpp/build/build_deploy_mingw.bat.tmpl",
        snake_name=sn,
        windeployqt_block=windeployqt_block,
    )


# -----------------------------------------------------------------------
# MSYS2 variant (pacman packages — most reliable MinGW path on Windows)
# -----------------------------------------------------------------------

def _set_env_msys2_bat(spec: "ScaffoldSpec") -> str:
    """MSYS2 env setup - uses MSYS2's mingw64 tree for toolchain + deps."""
    return load_template("cpp/build/set_env_msys2.bat.tmpl")


def _build_msys2_bat(spec: "ScaffoldSpec") -> str:
    """MSYS2 deploy script - uses MSYS2's native MinGW packages."""
    sn = spec.snake_name
    windeployqt_block = ""
    if spec.gui_type == "widget":
        windeployqt_block = load_template(
            "cpp/build/windeployqt.msys2.bat.tmpl", snake_name=sn)
    return load_template(
        "cpp/build/build_deploy_msys2.bat.tmpl",
        snake_name=sn,
        windeployqt_block=windeployqt_block,
    )


def _build_sh(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    gui_copy = ""
    if spec.gui_type == "widget":
        gui_copy = f'cp "$CLIENT_BUILD/{sn}_gui" "$DIST/" 2>/dev/null || true\n'
    return load_template(
        "cpp/build/build_deploy.sh.tmpl",
        snake_name=sn,
        gui_copy=gui_copy,
    )


# -----------------------------------------------------------------------
# Proto stub generation scripts (shared — live in proto/)
# -----------------------------------------------------------------------

def _gen_stubs_bat(spec: "ScaffoldSpec") -> str:
    return load_template(
        "cpp/build/generate_stubs.bat.tmpl",
        snake_name=spec.snake_name,
    )


def _gen_stubs_sh(spec: "ScaffoldSpec") -> str:
    return load_template(
        "cpp/build/generate_stubs.sh.tmpl",
        snake_name=spec.snake_name,
    )


def _build_wasm_bat(spec: "ScaffoldSpec") -> str:
    return load_template(
        "cpp/build/build_wasm.bat.tmpl",
        snake_name=spec.snake_name,
    )


def _build_wasm_sh(spec: "ScaffoldSpec") -> str:
    return load_template(
        "cpp/build/build_wasm.sh.tmpl",
        snake_name=spec.snake_name,
    )


# -----------------------------------------------------------------------
# QML GUI files
# -----------------------------------------------------------------------

def _qml_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    svc = spec.service_name
    return {
        "qml/ServiceUI.qml": load_template(
            "cpp/client/qml/ServiceUI.qml.tmpl", service_name=svc),
        "GUIs/ServiceUI.qml": load_template(
            "cpp/client/qml/ServiceUI.GUIs.qml.tmpl", service_name=svc),
        "stubs/MicroserviceBase/qmldir": load_template(
            "cpp/client/qml/qmldir.tmpl"),
        "stubs/MicroserviceBase/ServiceBridge.qml": load_template(
            "cpp/client/qml/ServiceBridge.qml.tmpl"),
    }


# -----------------------------------------------------------------------
# WASM GUI files
# -----------------------------------------------------------------------

def _wasm_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    svc = spec.service_name
    return {
        "wasm/main.cpp":      load_template("cpp/client/wasm/main.cpp.tmpl"),
        "src/MainWidget.h":   load_template("cpp/client/wasm/MainWidget.h.tmpl"),
        "src/MainWidget.cpp": load_template(
            "cpp/client/wasm/MainWidget.cpp.tmpl", service_name=svc),
        f"GUIs/{svc}.html":   load_template(
            "cpp/client/wasm/service.html.tmpl", service_name=svc),
    }


# -----------------------------------------------------------------------
# Widget GUI files
# -----------------------------------------------------------------------

def _widget_method_binding(m: "MethodSpec", sn: str, ns: str) -> str:
    """Emit one `MethodBinding` initializer block for `buildMethodBindings()`.

    Picks the right widget cast + req setter per proto type, and the right
    display expression for the response's `result` field.  Supports unary
    and server-streaming RPCs.  For imported protos (m.input_type /
    m.output_type set) we can't infer field names so we emit a
    compile-only skeleton: default request, status-only response.
    """
    imported = bool(m.input_type or m.output_type)
    inT  = ("::" + m.input_type.replace(".", "::"))  if m.input_type  else f"{ns}::{m.name}Request"
    outT = ("::" + m.output_type.replace(".", "::")) if m.output_type else f"{ns}::{m.name}Response"

    if imported:
        tmpl = ("cpp/client/widget/binding_imported_streaming.cpp.tmpl"
                if m.server_streaming
                else "cpp/client/widget/binding_imported_unary.cpp.tmpl")
        return load_template(
            tmpl,
            method_name=m.name,
            input_type=inT,
            output_type=outT,
        )

    # Wizard-generated proto (flat params, `result` field)
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

    tmpl = ("cpp/client/widget/binding_streaming.cpp.tmpl"
            if m.server_streaming
            else "cpp/client/widget/binding_unary.cpp.tmpl")
    return load_template(
        tmpl,
        method_name=m.name,
        input_type=inT,
        output_type=outT,
        params_init=params_init,
        setters_str=setters_str,
        ret_expr=ret_expr,
    )


def _widget_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    """Qt Widgets GUI *client* — lives under client/gui/, built alongside
    the console client by the same client/CMakeLists.txt.
    """
    svc = spec.service_name
    sn = spec.snake_name
    ns = spec.proto_namespace
    grpc_name = _grpc_svc_name(spec)

    method_blocks = "\n\n".join(
        _widget_method_binding(m, sn, ns) for m in spec.methods
    )

    return {
        "client/gui/main.cpp":      load_template("cpp/client/widget/main.cpp.tmpl"),
        "client/gui/MainWindow.h":  load_template(
            "cpp/client/widget/MainWindow.h.tmpl",
            snake_name=sn, proto_namespace=ns, grpc_name=grpc_name),
        "client/gui/MainWindow.cpp": load_template(
            "cpp/client/widget/MainWindow.cpp.tmpl",
            snake_name=sn, proto_namespace=ns, grpc_name=grpc_name,
            method_blocks=method_blocks),
        "client/gui/MainWindow.ui": load_template(
            "cpp/client/widget/MainWindow.ui.tmpl",
            service_name=svc),
    }


def _client_files(spec: "ScaffoldSpec") -> Dict[str, str]:
    sn = spec.snake_name
    ns = spec.proto_namespace
    svc = spec.service_name
    grpc_name = _grpc_svc_name(spec)

    gui_block = ""
    if spec.gui_type == "widget":
        gui_block = load_template(
            "cpp/client/subproject/gui_block.cmake.tmpl",
            snake_name=sn,
        )

    return {
        "client/CMakeLists.txt": load_template(
            "cpp/client/subproject/CMakeLists.txt.tmpl",
            snake_name=sn,
            service_name=svc,
            version=spec.version,
            deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
            gui_block=gui_block,
        ),
        "client/src/client.cpp": load_template(
            "cpp/client/subproject/client.cpp.tmpl",
            snake_name=sn,
            service_name=svc,
            proto_namespace=ns,
            grpc_name=grpc_name,
        ),
        "client/README.md": load_template(
            "cpp/client/subproject/README.md.tmpl",
            snake_name=sn,
            service_name=svc,
            grpc_name=grpc_name,
        ),
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
    sn = spec.snake_name
    proto_srcs_var = f"{sn.upper()}_PROTO_SRCS"
    proto_inc_var  = f"{sn.upper()}_PROTO_INC"

    exe_blocks = []
    seen_targets = set()
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        if svc_snake in seen_targets:
            continue
        seen_targets.add(svc_snake)
        exe_blocks.append(load_template(
            "cpp/monorepo/service_exe.cmake.tmpl",
            svc_snake=svc_snake,
            svc_pascal=svc.name,
            proto_srcs_var=proto_srcs_var,
            proto_inc_var=proto_inc_var,
        ))
    exe_joined = "\n".join(b.rstrip() for b in exe_blocks)

    return load_template(
        "cpp/monorepo/CMakeLists.txt.tmpl",
        project_name=spec.service_name,
        snake_name=sn,
        version=spec.version,
        proto_srcs_var=proto_srcs_var,
        proto_inc_var=proto_inc_var,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
        exe_blocks=exe_joined,
    )


def _mono_main_cpp(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    return load_template(
        "cpp/monorepo/main.cpp.tmpl",
        svc_snake=svc_snake,
        svc_pascal=svc.name,
        proto_package=spec.proto_package,
    )


def _mono_settings_h(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    return load_template(
        "cpp/monorepo/Settings.h.tmpl",
        svc_snake=svc_snake,
        env_prefix=svc_snake.upper() + "_",
    )


def _mono_domain_h(spec, svc) -> str:
    """Domain class is a placeholder — the user adds methods matching
    their proto's real request/response fields.  We intentionally don't
    guess signatures because we can't map arbitrary imported protos."""
    svc_snake = _mono_snake(svc.name)
    method_hints = "\n".join(
        f"    // rpc {m.name}(...)  -  wire in adapters/api/{svc.name}GrpcAdapter.cpp"
        for m in svc.methods
    ) or "    // (no methods declared in proto yet)"
    return load_template(
        "cpp/monorepo/domain.h.tmpl",
        svc_snake=svc_snake,
        svc_pascal=svc.name,
        svc_name=svc.name,
        method_hints=method_hints,
    )


def _mono_domain_cpp(spec, svc) -> str:
    return load_template(
        "cpp/monorepo/domain.cpp.tmpl",
        svc_snake=_mono_snake(svc.name),
        svc_pascal=svc.name,
    )


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
    ns = spec.proto_namespace
    svc_snake = _mono_snake(svc.name)
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
    return load_template(
        "cpp/monorepo/adapter.h.tmpl",
        svc_snake=svc_snake,
        svc_pascal=svc.name,
        snake_name=spec.snake_name,
        proto_namespace=ns,
        methods=methods,
    )


def _mono_adapter_cpp(spec, svc) -> str:
    """Adapter bodies are placeholders — user fills in marshaling logic.

    For arbitrary imported protos we can't infer how the user's domain
    class maps to their specific request/response fields, so we emit a
    safe-compiling `UNIMPLEMENTED` stub with TODO markers.
    """
    ns = spec.proto_namespace
    svc_snake = _mono_snake(svc.name)
    methods_parts = []
    for m in svc.methods:
        inT  = _mono_input_cpp_type(m, ns)
        outT = _mono_output_cpp_type(m, ns)
        tmpl = ("cpp/monorepo/adapter.cpp.method_streaming.tmpl"
                if m.server_streaming
                else "cpp/monorepo/adapter.cpp.method_unary.tmpl")
        methods_parts.append(load_template(
            tmpl,
            svc_pascal=svc.name,
            method_name=m.name,
            input_type=inT,
            output_type=outT,
        ))
    methods = "".join(methods_parts)
    return load_template(
        "cpp/monorepo/adapter.cpp.tmpl",
        svc_snake=svc_snake,
        svc_pascal=svc.name,
        methods=methods,
    )


def _mono_nomad(spec, svc) -> str:
    """Per-service Nomad HCL spec."""
    svc_snake = _mono_snake(svc.name)
    return load_template(
        "cpp/monorepo/service.nomad.hcl.tmpl",
        svc_snake=svc_snake,
        svc_name=svc.name,
        project_name=spec.service_name,
        env_prefix=svc_snake.upper() + "_",
        datacenter=getattr(spec, 'nomad_dc', 'dc1') or 'dc1',
        driver=getattr(spec, 'nomad_driver', 'raw_exec') or 'raw_exec',
        cpu=getattr(spec, 'nomad_cpu', 100) or 100,
        mem=getattr(spec, 'nomad_mem', 128) or 128,
        consul_addr=getattr(spec, 'nomad_consul_addr', '') or 'http://127.0.0.1:8500',
    )


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
    exe_copies = "\n".join(
        f'xcopy /Y /Q "%SERVICE_BUILD%\\Release\\{_mono_snake(s.name)}.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    client_copies = "\n".join(
        f'xcopy /Y /Q "%CLIENT_BUILD%\\Release\\{_mono_snake(s.name)}_client.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    return load_template(
        "cpp/monorepo/build_deploy.bat.tmpl",
        snake_name=spec.snake_name,
        exe_copies=exe_copies,
        client_copies=client_copies,
    )


def _mono_build_sh(spec, services) -> str:
    exe_copies = "\n".join(
        f'cp "$SERVICE_BUILD/{_mono_snake(s.name)}"        "$DIST/" 2>/dev/null || true'
        for s in services
    )
    client_copies = "\n".join(
        f'cp "$CLIENT_BUILD/{_mono_snake(s.name)}_client" "$DIST/" 2>/dev/null || true'
        for s in services
    )
    return load_template(
        "cpp/monorepo/build_deploy.sh.tmpl",
        snake_name=spec.snake_name,
        exe_copies=exe_copies,
        client_copies=client_copies,
    )


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

    rationale_html = ""
    if svc_uses_vcpkg or cli_uses_vcpkg:
        vcpkg_manifest_name = spec.snake_name.replace('_', '-') + '-server-vcpkg'
        rationale_html = load_template(
            "cpp/monorepo/readme_html_rationale.html.tmpl",
            vcpkg_manifest_name=vcpkg_manifest_name,
        )

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
        full_kit_walkthrough_html = load_template(
            "cpp/monorepo/readme_html_full_kit_walkthrough.html.tmpl"
        )

    # ---- Qt Creator setup ----
    if svc_uses_vcpkg or cli_uses_vcpkg:
        qtc_html = load_template("cpp/monorepo/readme_html_qtc_vcpkg.html.tmpl")
    else:
        qtc_html = load_template("cpp/monorepo/readme_html_qtc_msys2.html.tmpl")

    # ---- Prebuilt libraries (download + use) ----
    prebuilt_html = ""
    if svc_uses_vcpkg or cli_uses_vcpkg:
        prebuilt_html = load_template("cpp/monorepo/readme_html_prebuilt.html.tmpl")

    # ---- Run sequence ----
    # Build Nomad job table per service so user has copy-pasteable commands.
    nomad_rows = "\n".join(
        f'        <tr><td><code>{s.name}</code></td>'
        f'<td><pre><code>nomad job run deploy\\{_mono_snake(s.name)}.nomad.hcl</code></pre></td>'
        f'<td><pre><code>nomad job stop {_mono_snake(s.name)}</code></pre></td></tr>'
        for s in services
    )
    run_html = load_template(
        "cpp/monorepo/readme_html_run.html.tmpl",
        nomad_rows=nomad_rows,
    )

    trouble_items = []
    if svc_uses_vcpkg or cli_uses_vcpkg:
        trouble_items.append((
            'Qt Creator: <code>Could not find a package configuration file provided by &quot;gRPC&quot;</code>',
            load_template("cpp/monorepo/readme_html_trouble_qtc_grpc_not_found.html.tmpl"),
        ))
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
                load_template("cpp/monorepo/readme_html_trouble_f5_dll.html.tmpl"),
            ))
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
        load_template("cpp/monorepo/readme_html_trouble_abi_debugger.html.tmpl"),
    ))
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

    rationale_or_default = rationale_html if rationale_html else (
        '    <p>This scaffold uses MSYS2&rsquo;s prebuilt grpc/protobuf - see '
        '<code>examples/docs/html/mingw_setup.html</code> for the toolchain story.</p>'
    )
    prebuilt_section = (
        '<section id="prebuilt"><h2>Use prebuilt libraries '
        '(skip the 30-60 min vcpkg compile)</h2>' + prebuilt_html + '</section>'
    ) if prebuilt_html else ''
    nav_rationale = '<a href="#rationale">How vcpkg + Qt MinGW works</a>'         if (svc_uses_vcpkg or cli_uses_vcpkg) else ''
    nav_prebuilt = '<a href="#prebuilt">Use prebuilt libraries</a>'         if (svc_uses_vcpkg or cli_uses_vcpkg) else ''
    return load_template(
        "cpp/monorepo/readme_html_shell.html.tmpl",
        proj=proj,
        snake_name=spec.snake_name,
        server_grpc_kind=spec.server_grpc_kind,
        client_grpc_kind=spec.client_grpc_kind,
        gui_type=spec.gui_type,
        svc_rows=svc_rows,
        quick_rows=quick_rows,
        prereq_html=prereq_html,
        env_section_html=_readme_env_section_html(svc_uses_vcpkg or cli_uses_vcpkg, has_qt6_grpc_client),
        rationale_html=rationale_or_default,
        cli_html=cli_html,
        qtc_html=qtc_html,
        run_html=run_html,
        trouble_html=trouble_html,
        full_kit_walkthrough_html=full_kit_walkthrough_html,
        prebuilt_section=prebuilt_section,
        nav_rationale=nav_rationale,
        nav_prebuilt=nav_prebuilt,
    )


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
        full_kit_walkthrough_md = load_template(
            "cpp/monorepo/readme_full_kit_walkthrough.md.tmpl"
        )
    qtc_section = ""
    if svc_uses_vcpkg or cli_uses_vcpkg:
        qtc_section = load_template(
            "cpp/monorepo/readme_qtc_section.md.tmpl"
        )
    return load_template(
        "cpp/monorepo/README.md.tmpl",
        service_name=spec.service_name,
        snake_name=spec.snake_name,
        n_services=len(services),
        svc_lines=svc_lines,
        full_kit_walkthrough_md=full_kit_walkthrough_md,
        qtc_section=qtc_section,
    )



# ----------------------------------------------------------------------
# Monorepo: MinGW + MSYS2 build variants
# ----------------------------------------------------------------------

def _mono_build_mingw_bat(spec, services) -> str:
    exe_copies = "\n".join(
        f'xcopy /Y /Q "%SERVICE_BUILD%\\{_mono_snake(s.name)}.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    client_copies = "\n".join(
        f'xcopy /Y /Q "%CLIENT_BUILD%\\{_mono_snake(s.name)}_client.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    return load_template(
        "cpp/monorepo/build_deploy_mingw.bat.tmpl",
        snake_name=spec.snake_name,
        exe_copies=exe_copies,
        client_copies=client_copies,
    )


def _mono_build_msys2_bat(spec, services) -> str:
    project_snake = spec.snake_name
    exe_copies = "\n".join(
        f'xcopy /Y /Q "%SERVICE_BUILD%\\{_mono_snake(s.name)}.exe" "%DIST%\\" >nul 2>&1'
        for s in services
    )
    client_copies_list = [
        f'xcopy /Y /Q "%CLIENT_BUILD%\\{project_snake}_client.exe" "%DIST%\\" >nul 2>&1'
    ]
    if spec.gui_type in ("widget", "wasm", "qml"):
        client_copies_list.append(
            f'xcopy /Y /Q "%CLIENT_BUILD%\\{project_snake}_gui.exe" "%DIST%\\" >nul 2>&1')
    client_copies = "\n".join(client_copies_list)

    launcher_names = [_mono_snake(s.name) for s in services]
    launcher_names.append(f"{project_snake}_client")
    if spec.gui_type in ("widget", "wasm", "qml"):
        launcher_names.append(f"{project_snake}_gui")
    gui_launcher_name = f"{project_snake}_gui" if spec.gui_type in ("widget", "wasm", "qml") else None

    launcher_lines = []
    for n in launcher_names:
        if n == gui_launcher_name:
            launcher_lines.append(f'call :emit_gui_launcher "%DIST%\\run_{n}.bat" "{n}.exe"')
        else:
            launcher_lines.append(f'call :emit_launcher "%DIST%\\run_{n}.bat" "{n}.exe"')
    launcher_block = "\n".join(launcher_lines)

    windeployqt_block = ""
    if spec.gui_type in ("widget", "wasm"):
        windeployqt_block = load_template(
            "cpp/monorepo/windeployqt_widget.bat.tmpl",
            project_snake=project_snake)
    elif spec.gui_type == "qml":
        windeployqt_block = load_template(
            "cpp/monorepo/windeployqt_qml.bat.tmpl",
            project_snake=project_snake)

    return load_template(
        "cpp/monorepo/build_deploy_msys2.bat.tmpl",
        snake_name=spec.snake_name,
        exe_copies=exe_copies,
        client_copies=client_copies,
        launcher_block=launcher_block,
        windeployqt_block=windeployqt_block,
    )


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
        f"- **{s.name}** -- {len(s.methods)} RPC method(s)" for s in services
    )
    ui_section = ""
    if ui_kind in ("widget", "wasm"):
        ui_section = load_template(
            "cpp/monorepo/client/ui_section_widget.md.tmpl",
            project_snake=project_snake,
        )
        if ui_kind == "wasm":
            ui_section += load_template(
                "cpp/monorepo/client/ui_section_wasm.md.tmpl")
    elif ui_kind == "qml":
        ui_section = load_template(
            "cpp/monorepo/client/ui_section_qml.md.tmpl",
            project_snake=project_snake,
        )

    files["client/README.md"] = load_template(
        "cpp/monorepo/client/README.md.tmpl",
        service_name=spec.service_name,
        project_snake=project_snake,
        svc_list=svc_list,
        ui_section=ui_section,
    )
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
        gui_block = load_template(
            "cpp/monorepo/client/gui_block_widget_wasm.cmake.tmpl",
            ui_kind=ui_kind,
            project_snake=project_snake,
        )
    elif ui_kind == "qml":
        gui_block = load_template(
            "cpp/monorepo/client/gui_block_qml.cmake.tmpl",
            project_snake=project_snake,
        )

    return load_template(
        "cpp/monorepo/client/CMakeLists.txt.tmpl",
        snake_name=sn,
        service_name=spec.service_name,
        version=spec.version,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
        console_sources=console_sources,
        gui_block=gui_block,
    )


def _mono_client_registry_h() -> str:
    return load_template("cpp/monorepo/client/client_registry.h.tmpl")


def _mono_client_registry_cpp(spec, services) -> str:
    sn = spec.snake_name
    ns = spec.proto_namespace

    client_slots = []
    getter_fns = []
    for svc in services:
        svc_pascal = svc.name
        svc_snake = _mono_snake(svc.name)
        client_slots.append(
            f"    std::unique_ptr<microservice_base::ServiceClient<{ns}::{svc_pascal}>> "
            f"g_{svc_snake}_client;")
        getter_fns.append(
            f"    microservice_base::ServiceClient<{ns}::{svc_pascal}>&\n"
            f"    get_{svc_snake}_client() {{\n"
            f"        if (!g_{svc_snake}_client) {{\n"
            f"            if (!g_direct_host.empty())\n"
            f"                g_{svc_snake}_client = std::make_unique<\n"
            f"                    microservice_base::ServiceClient<{ns}::{svc_pascal}>>(\n"
            f'                        "{svc_snake}", g_direct_host, true);\n'
            f"            else\n"
            f"                g_{svc_snake}_client = std::make_unique<\n"
            f"                    microservice_base::ServiceClient<{ns}::{svc_pascal}>>(\n"
            f'                        "{svc_snake}", g_consul_addr);\n'
            f"        }}\n"
            f"        return *g_{svc_snake}_client;\n"
            f"    }}")

    svc_labels = ", ".join(f'"{s.name}"' for s in services)

    methods_cases = []
    for svc in services:
        method_labels = ", ".join(f'"{m.name}"' for m in svc.methods)
        methods_cases.append(
            f'    if (serviceName == "{svc.name}") return {{ {method_labels} }};')
    methods_body = "\n".join(methods_cases) if methods_cases else "    (void)serviceName;"

    _streaming_tmpl = ('    if (serviceName == "{svc_name}" && methodName == "{m_name}") {{\n        return {{ false, "{m_name}: streaming RPCs are not supported by the JSON UI client." }};\n    }}')
    _unary_tmpl = ('    if (serviceName == "{svc_name}" && methodName == "{m_name}") {{\n        {inT} req;\n        auto s0 = google::protobuf::util::JsonStringToMessage(requestJson, &req);\n        if (!s0.ok()) return {{ false, std::string("JSON parse: ") + s0.ToString() }};\n        {outT} resp;\n        grpc::ClientContext ctx;\n        grpc::Status st;\n        try {{\n            auto& c = get_{svc_snake}_client();\n            st = c.stub().{m_name}(&ctx, req, &resp);\n        }} catch (const std::exception& e) {{\n            return {{ false, std::string("Connect failed: ") + e.what() }};\n        }}\n        if (!st.ok()) return {{ false, std::string("RPC failed: ") + st.error_message() }};\n        std::string out;\n        google::protobuf::util::JsonPrintOptions opts;\n        opts.add_whitespace = true;\n        auto s1 = google::protobuf::util::MessageToJsonString(resp, &out, opts);\n        if (!s1.ok()) return {{ false, std::string("JSON serialize: ") + s1.ToString() }};\n        return {{ true, out }};\n    }}')
    invoke_cases = []
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        for m in svc.methods:
            inT  = _mono_input_cpp_type(m, ns)
            outT = _mono_output_cpp_type(m, ns)
            if m.server_streaming:
                invoke_cases.append(_streaming_tmpl.format(svc_name=svc.name, m_name=m.name).replace("{{", "{").replace("}}", "}"))
            else:
                invoke_cases.append(_unary_tmpl.format(svc_name=svc.name, m_name=m.name, inT=inT, outT=outT, svc_snake=svc_snake).replace("{{", "{").replace("}}", "}"))
    invoke_body = "\n".join(invoke_cases)

    reset_stmts = "\n".join(
        f"    g_{_mono_snake(s.name)}_client.reset();" for s in services
    )

    return load_template(
        "cpp/monorepo/client/client_registry.cpp.tmpl",
        snake_name=sn,
        client_slots="\n".join(client_slots),
        getter_fns="\n".join(getter_fns),
        reset_stmts=reset_stmts,
        svc_labels=svc_labels,
        methods_body=methods_body,
        invoke_body=invoke_body,
    )


# ----------------------------------------------------------------------
# Monorepo: Qt Widgets UI client
# ----------------------------------------------------------------------

def _mono_widget_main_cpp() -> str:
    return load_template("cpp/monorepo/client/widget_main.cpp.tmpl")


def _mono_widget_mainwindow_h() -> str:
    return load_template("cpp/monorepo/client/widget_mainwindow.h.tmpl")


def _mono_widget_mainwindow_cpp(spec) -> str:
    return load_template(
        "cpp/monorepo/client/widget_mainwindow.cpp.tmpl",
        title=f"{spec.service_name} Client",
    )


# ----------------------------------------------------------------------
# Monorepo: WASM build scripts (reuses the Widget client)
# ----------------------------------------------------------------------

def _mono_wasm_build_bat(spec) -> str:
    return load_template(
        "cpp/monorepo/client/wasm_build.bat.tmpl",
        project_snake=spec.snake_name,
    )


def _mono_wasm_build_sh(spec) -> str:
    return load_template(
        "cpp/monorepo/client/wasm_build.sh.tmpl",
        project_snake=spec.snake_name,
    )


# ----------------------------------------------------------------------
# Monorepo: Qt Quick (QML) UI client
# ----------------------------------------------------------------------

def _mono_qml_main_cpp(spec) -> str:
    return load_template(
        "cpp/monorepo/client/qml_main.cpp.tmpl",
        project_snake=spec.snake_name,
    )


def _mono_qml_bridge_h() -> str:
    return load_template("cpp/monorepo/client/qml_bridge.h.tmpl")


def _mono_qml_bridge_cpp() -> str:
    return load_template("cpp/monorepo/client/qml_bridge.cpp.tmpl")


def _mono_qml_main_qml(spec) -> str:
    return load_template(
        "cpp/monorepo/client/qml_main.qml.tmpl",
        title=f"{spec.service_name} Client",
    )


def _mono_client_common_h() -> str:
    return load_template("cpp/monorepo/client/client_common.h.tmpl")


def _mono_client_main_cpp(spec, services) -> str:
    project_snake = spec.snake_name
    includes = "\n".join(
        f'#include "{_mono_snake(s.name)}_menu.h"' for s in services
    )
    labels = ", ".join(f'"{s.name}"' for s in services)
    dispatch_cases = "\n".join(
        f"            case {i+1}: {_mono_snake(s.name)}_menu::run(); break;"
        for i, s in enumerate(services)
    )
    return load_template(
        "cpp/monorepo/client/main.cpp.tmpl",
        project_name=spec.service_name,
        project_snake=project_snake,
        includes=includes,
        labels=labels,
        dispatch_cases=dispatch_cases,
    )


def _mono_client_menu_h(spec, svc) -> str:
    return load_template(
        "cpp/monorepo/client/menu.h.tmpl",
        svc_snake=_mono_snake(svc.name),
        svc_name=svc.name,
    )


def _mono_client_menu_cpp(spec, svc) -> str:
    """Interactive per-service menu: resolves the stub, then loops showing
    a list of RPC methods.  Each method is invoked with a default request
    (for imported protos) or sample values (for wizard-generated protos)."""
    sn = spec.snake_name
    ns = spec.proto_namespace
    svc_pascal = svc.name
    svc_snake = _mono_snake(svc.name)

    method_labels = ", ".join(f'"{m.name}"' for m in svc.methods)

    cases = []
    for idx, m in enumerate(svc.methods, start=1):
        inT = _mono_input_cpp_type(m, ns)
        outT = _mono_output_cpp_type(m, ns)
        imported = bool(m.input_type or m.output_type)

        if imported:
            cases.append(load_template(
                "cpp/monorepo/client/case_imported.cpp.tmpl",
                idx=idx, inT=inT, outT=outT, method=m.name,
            ))
            continue

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
        print_expr = '(resp.result() ? "true" : "false")' if rt == "bool" else "resp.result()"

        tmpl = "cpp/monorepo/client/case_streaming.cpp.tmpl" if m.server_streaming \
            else "cpp/monorepo/client/case_unary.cpp.tmpl"
        cases.append(load_template(
            tmpl,
            idx=idx, inT=inT, outT=outT, method=m.name,
            setters=setters, print_expr=print_expr,
        ))

    cases_joined = "\n".join(cases) if cases \
        else '            default: std::cout << "(no methods)\\n"; break;'

    return load_template(
        "cpp/monorepo/client/service_menu.cpp.tmpl",
        svc_pascal=svc_pascal, svc_snake=svc_snake, sn=sn, ns=ns,
        method_labels=method_labels, cases_joined=cases_joined,
    )


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
        proto_blocks.append(load_template(
            "cpp/mp/client_proto_block.cmake.tmpl",
            basename=basename, var=var, proto_filename=proto_filename,
        ))

    proto_codegen = '\n'.join(proto_blocks)
    src_var_uses = '\n    '.join(src_lists)

    return load_template(
        "cpp/mp/client_CMakeLists.txt.tmpl",
        project_name=project_name,
        version=spec.version,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
        proto_codegen=proto_codegen,
        src_var_uses=src_var_uses,
        sn=sn,
    )



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

    return load_template(
        "cpp/mp/client_main.cpp.tmpl",
        project_name=project_name, sn=sn, sn_upper=sn.upper(),
        inc_block=inc_block, stub_block=stub_block, list_block=list_block,
    )


def _mp_client_readme(spec, services) -> str:
    sn = spec.snake_name
    svc_lines = "\n".join(
        f"- **{svc.name}** (proto package `{_mp_proto_package(svc)}`)"
        for svc in services
    )
    return load_template(
        "cpp/mp/client_README.md.tmpl",
        service_name=spec.service_name, sn=sn, sn_upper=sn.upper(),
        svc_lines=svc_lines,
    )


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

    return load_template(
        "cpp/mp/qt_client_grpcpp_CMakeLists.txt.tmpl",
        service_name=spec.service_name,
        version=spec.version,
        proto_files_block=proto_files_block,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
        sn=sn,
    )



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
    return load_template(
        "cpp/mp/Settings.h.tmpl",
        snake_name=sn,
        service_name=spec.service_name,
        env_prefix=sn.upper() + "_",
    )


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
        pkg = _mp_proto_package(svc)
        includes.append(f'#include "{svc_snake}/domain/{svc_pascal}.h"')
        includes.append(f'#include "{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.h"')
        instances.append(f"        {svc_snake}::{svc_pascal} {svc_snake}Domain;")
        adapters.append(
            f"        {svc_snake}::{svc_pascal}GrpcAdapter "
            f"{svc_snake}Adapter({svc_snake}Domain);"
        )
        add_calls.append(
            f'        runner.addService(&{svc_snake}Adapter, '
            f'"{pkg}.{svc_pascal}");'
        )
    return load_template(
        "cpp/mp/main.cpp.tmpl",
        snake_name=sn,
        services_count=len(services),
        inc_block="\n".join(includes),
        inst_block="\n".join(instances),
        adapt_block="\n".join(adapters),
        add_block="\n".join(add_calls),
    )


# -------- Per-service domain --------
def _mp_domain_h(spec, svc) -> str:
    svc_snake = _mono_snake(svc.name)
    method_hints = "\n".join(
        f"    // rpc {m.name}(...)  -  wire in adapters/api/{svc.name}GrpcAdapter.cpp"
        for m in svc.methods
    ) or "    // (no methods declared in proto yet)"
    return load_template(
        "cpp/mp/domain.h.tmpl",
        svc_snake=svc_snake,
        svc_pascal=svc.name,
        svc_name=svc.name,
        method_hints=method_hints,
    )


def _mp_domain_cpp(spec, svc) -> str:
    return load_template(
        "cpp/mp/domain.cpp.tmpl",
        svc_snake=_mono_snake(svc.name),
        svc_pascal=svc.name,
    )


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
    ns = _mp_proto_namespace(svc)
    method_decls = "\n".join(
        f'    grpc::Status {m.name}(grpc::ServerContext* ctx,\n'
        f'        const {_mp_input_cpp_type(m, ns)}* request,\n'
        f'        {_mp_output_cpp_type(m, ns)}* response) override;'
        for m in svc.methods
    )
    return load_template(
        "cpp/mp/adapter.h.tmpl",
        svc_snake=_mono_snake(svc.name),
        svc_pascal=svc.name,
        basename=_mp_proto_basename(svc),
        proto_namespace=ns,
        method_decls=method_decls,
    )


def _mp_adapter_cpp(spec, svc) -> str:
    ns = _mp_proto_namespace(svc)
    method_impls = "\n\n".join(
        f'grpc::Status {svc.name}GrpcAdapter::{m.name}(\n'
        f'    grpc::ServerContext* /*ctx*/,\n'
        f'    const {_mp_input_cpp_type(m, ns)}* /*request*/,\n'
        f'    {_mp_output_cpp_type(m, ns)}* /*response*/) {{\n'
        f'    // TODO: read fields from `request`, call m_domain, populate `response`.\n'
        f'    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement {m.name}");\n'
        f'}}'
        for m in svc.methods
    )
    return load_template(
        "cpp/mp/adapter.cpp.tmpl",
        svc_snake=_mono_snake(svc.name),
        svc_pascal=svc.name,
        method_impls=method_impls,
    )


# -------- CMakeLists: N proto codegens + 1 add_executable --------
def _mp_cmake(spec, services) -> str:
    sn = spec.snake_name
    codegen_blocks = []
    proto_src_lists = []
    seen_basenames = set()
    for svc in services:
        basename = _mp_proto_basename(svc)
        if basename in seen_basenames:
            continue
        seen_basenames.add(basename)
        proto_filename = _mp_proto_filename(svc)
        var = basename.upper() + "_SRCS"
        proto_src_lists.append("${" + var + "}")
        codegen_blocks.append(_mp_proto_codegen_block(proto_filename, basename, var))
    codegen_joined = "\n".join(codegen_blocks)
    proto_srcs_var_uses = "\n    ".join(proto_src_lists)

    per_svc_srcs = ['    src/Settings.h']
    for svc in services:
        svc_snake = _mono_snake(svc.name)
        svc_pascal = svc.name
        per_svc_srcs.append(f'    src/{svc_snake}/domain/{svc_pascal}.h')
        per_svc_srcs.append(f'    src/{svc_snake}/domain/{svc_pascal}.cpp')
        per_svc_srcs.append(f'    src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.h')
        per_svc_srcs.append(f'    src/{svc_snake}/adapters/api/{svc_pascal}GrpcAdapter.cpp')
    per_svc_block = "\n".join(per_svc_srcs)

    return load_template(
        "cpp/mp/CMakeLists.txt.tmpl",
        project_name=spec.service_name,
        version=spec.version,
        snake_name=sn,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
        codegen_joined=codegen_joined,
        per_svc_block=per_svc_block,
        proto_srcs_var_uses=proto_srcs_var_uses,
    )


def _mp_proto_codegen_block(proto_filename: str, basename: str, var: str) -> str:
    """Emit the add_custom_command + variable for one .proto's codegen."""
    return load_template(
        "cpp/mp/proto_codegen_block.cmake.tmpl",
        proto_filename=proto_filename,
        basename=basename,
        var=var,
    )


# -------- Nomad job (one job, one .exe, one port) --------
def _mp_nomad(spec, services) -> str:
    sn = spec.snake_name
    return load_template(
        "cpp/mp/service.nomad.hcl.tmpl",
        snake_name=sn,
        service_name=spec.service_name,
        services_count=len(services),
        services_list=", ".join(svc.name for svc in services),
        env_prefix=sn.upper() + "_",
        datacenter=spec.nomad_dc,
        driver=spec.nomad_driver,
        consul_addr=spec.nomad_consul_addr,
        cpu=spec.nomad_cpu,
        mem=spec.nomad_mem,
    )


# -------- Build scripts (single .exe — simpler than monorepo's N-exe loop) --------
def _mp_build_bat(spec) -> str:
    return load_template(
        "cpp/mp/build.bat.tmpl",
        snake_name=spec.snake_name,
        service_name=spec.service_name,
    )


def _mp_build_sh(spec) -> str:
    return load_template(
        "cpp/mp/build.sh.tmpl",
        snake_name=spec.snake_name,
        service_name=spec.service_name,
    )


# -------- Stub-gen helpers (walk all .proto files in proto/) --------
def _mp_gen_stubs_bat(spec, services) -> str:
    return load_template(
        "cpp/mp/gen_stubs.bat.tmpl",
        proto_list=" ".join(_mp_proto_filename(svc) for svc in services),
    )


def _mp_gen_stubs_sh(spec, services) -> str:
    return load_template(
        "cpp/mp/gen_stubs.sh.tmpl",
        proto_list=" ".join(_mp_proto_filename(svc) for svc in services),
    )


# -------- README --------
def _mp_readme(spec, services) -> str:
    sn = spec.snake_name
    svc_lines = "\n".join(
        f"- **{svc.name}** — proto `{_mp_proto_filename(svc)}`, "
        f"package `{_mp_proto_package(svc)}`, "
        f"{len(svc.methods)} method(s)"
        for svc in services
    )

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

    proto_tree = "\n".join(
        f"│   ├── {_mp_proto_filename(svc)}" for svc in services
    )
    description = spec.description or (spec.service_name + ' multi-service binary.')

    return load_template(
        "cpp/mp/README.md.tmpl",
        service_name=spec.service_name,
        description=description,
        n_services=len(services),
        svc_lines=svc_lines,
        proto_tree=proto_tree,
        svc_tree=svc_tree,
        sn=sn,
        sn_upper=sn.upper(),
    )


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
    return load_template(
        "cpp/qt_client/CMakeLists.txt.tmpl",
        project=f"{spec.service_name}QtClient",
        version=spec.version,
        snake_name=spec.snake_name,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
    )


def _qt_client_main_cpp(spec) -> str:
    return load_template("cpp/qt_client/main.cpp.tmpl")


def _qt_client_mainwindow_h() -> str:
    return load_template("cpp/qt_client/MainWindow.h.tmpl")


def _qt_client_mainwindow_ui(spec) -> str:
    """Qt Designer-editable .ui file — defines the form layout that
    ``ui->setupUi(this)`` instantiates at runtime.  AUTOUIC generates
    ``ui_MainWindow.h`` from this at build time."""
    return load_template(
        "cpp/qt_client/MainWindow.ui.tmpl",
        title=f"{spec.service_name} (Qt Client)",
    )


def _qt_client_mainwindow_cpp(spec, services) -> str:
    """Generate a MainWindow with a per-(service, method) JSON dispatch
    table.  Each entry parses the JSON request into the typed Qt-style
    Request, fires the RPC, and serialises the typed Response back to
    JSON for display - works uniformly for any .proto without
    per-method hand-coding.
    """
    sn = spec.snake_name
    ns = spec.proto_namespace

    entries = []
    if services:
        for s in services:
            entries.append((s.name, f"{ns}::{s.name}",
                            _mono_snake(s.name), s.methods))
    else:
        grpc_name = _grpc_svc_name(spec)
        entries.append((grpc_name, f"{ns}::{grpc_name}",
                        _snake(grpc_name), spec.methods or []))

    accessors = []
    for display, class_, snake, _methods in entries:
        accessors.append(
            f"{class_}::Client& {snake}_client() {{ static {class_}::Client c; return c; }}")
    accessors_block = "\n".join(accessors)

    attach_lines = "\n        ".join(
        f"{snake}_client().attachChannel(m_channel);"
        for _, _, snake, _ in entries
    )

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

    return load_template(
        "cpp/qt_client/MainWindow.cpp.tmpl",
        snake_name=sn,
        accessors_block=accessors_block,
        attach_lines=attach_lines,
        dispatch_body=dispatch_body,
    )


def _qt_client_build_bat(spec) -> str:
    return load_template(
        "cpp/qt_client/build_qt.bat.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_build_sh(spec) -> str:
    return load_template(
        "cpp/qt_client/build_qt.sh.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_build_deploy_bat(spec) -> str:
    return load_template(
        "cpp/qt_client/build_deploy_qt.bat.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_build_deploy_sh(spec) -> str:
    return load_template(
        "cpp/qt_client/build_deploy_qt.sh.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_gen_stubs_bat(spec) -> str:
    return load_template(
        "cpp/qt_client/generate_qt_stubs.bat.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_gen_stubs_sh(spec) -> str:
    return load_template(
        "cpp/qt_client/generate_qt_stubs.sh.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_readme(spec, services) -> str:
    if services:
        svc_block = "\n".join(f"- **{s.name}** -- {len(s.methods)} RPC method(s)" for s in services)
    else:
        svc_block = f"- **{spec.service_name}** -- {len(spec.methods or [])} RPC method(s)"
    return load_template(
        "cpp/qt_client/README.md.tmpl",
        service_name=spec.service_name,
        snake_name=spec.snake_name,
        svc_block=svc_block,
    )


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
    return load_template(
        "cpp/vcpkg/qt_grpcpp_vcpkg.json.tmpl",
        snake_hyphen=spec.snake_name.replace('_', '-'),
        version=spec.version,
    )


def _server_vcpkg_json(spec) -> str:
    return load_template(
        "cpp/vcpkg/server_vcpkg.json.tmpl",
        snake_hyphen=spec.snake_name.replace('_', '-'),
        version=spec.version,
    )


def _vcpkg_triplet_main() -> str:
    return load_template("cpp/vcpkg/triplet_main.cmake.tmpl")


def _vcpkg_triplet_chainload() -> str:
    return load_template("cpp/vcpkg/triplet_chainload.cmake.tmpl")


def _vcpkg_grpc_ice_patch() -> str:
    return load_raw("cpp/vcpkg/grpc_ice_patch.diff.tmpl")


def _vcpkg_init_overlay_bat() -> str:
    return load_template("cpp/vcpkg/init_vcpkg_overlay.bat.tmpl")


def _vcpkg_import_prebuilt_bat() -> str:
    return load_template("cpp/vcpkg/import_prebuilt.bat.tmpl")


def _vcpkg_export_prebuilt_bat() -> str:
    return load_template("cpp/vcpkg/export_prebuilt.bat.tmpl")


def _vcpkg_prep_nomad_paths_bat() -> str:
    return load_template("cpp/vcpkg/prep_nomad_paths.bat.tmpl")


def _vcpkg_cmake_presets_json(spec) -> str:
    return load_template(
        "cpp/vcpkg/cmake_presets.json.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_grpcpp_cmake_presets() -> str:
    return load_template("cpp/vcpkg/qt_grpcpp_cmake_presets.json.tmpl")


def _qt_client_grpcpp_cmake(spec) -> str:
    return load_template(
        "cpp/vcpkg/qt_grpcpp_CMakeLists.txt.tmpl",
        snake_name=spec.snake_name,
        service_name=spec.service_name,
        version=spec.version,
        deploy_runtime_block=_MB_DEPLOY_RUNTIME_BLOCK,
    )


def _qt_client_grpcpp_main_cpp(spec) -> str:
    return load_template("cpp/vcpkg/qt_grpcpp_main.cpp.tmpl")


def _qt_client_grpcpp_mainwindow_h(spec, services=None) -> str:
    sn = spec.snake_name
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

    return load_template(
        "cpp/vcpkg/qt_grpcpp_MainWindow.h.tmpl",
        proto_inc_block=proto_inc_block,
    )


def _qt_client_grpcpp_mainwindow_cpp(spec, services) -> str:
    """Generate MainWindow.cpp with one dispatch entry per (service, method)
    pair, using Google grpc++ sync stubs on a QtConcurrent::run worker.
    """
    is_multi = spec.layout == "multi_proto"
    project_ns = spec.proto_namespace

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

    return load_template(
        "cpp/vcpkg/qt_grpcpp_MainWindow.cpp.tmpl",
        dispatch_body=dispatch_body,
    )


def _qt_client_grpcpp_build_qt_bat(spec) -> str:
    return load_template(
        "cpp/vcpkg/qt_grpcpp_build_qt.bat.tmpl",
        snake_name=spec.snake_name,
        service_name=spec.service_name,
    )


def _qt_client_grpcpp_deploy_qt_bat(spec) -> str:
    return load_template(
        "cpp/vcpkg/qt_grpcpp_deploy_qt.bat.tmpl",
        snake_name=spec.snake_name,
    )


def _qt_client_grpcpp_export_prebuilt_bat(spec) -> str:
    return load_template("cpp/vcpkg/qt_grpcpp_export_prebuilt.bat.tmpl")


def _client_deploy_qt_vcpkg_bat(spec) -> str:
    return load_template(
        "cpp/vcpkg/client_deploy_qt_vcpkg.bat.tmpl",
        snake_name=spec.snake_name,
        service_name=spec.service_name,
    )


def _server_deploy_qt_vcpkg_bat(spec) -> str:
    return load_template(
        "cpp/vcpkg/server_deploy_qt_vcpkg.bat.tmpl",
        snake_name=spec.snake_name,
    )


def _server_build_qt_vcpkg_bat(spec) -> str:
    return load_template(
        "cpp/vcpkg/server_build_qt_vcpkg.bat.tmpl",
        service_name=spec.service_name,
    )


def _qt_client_grpcpp_readme(spec) -> str:
    return load_template(
        "cpp/vcpkg/qt_grpcpp_readme.md.tmpl",
        snake_name=spec.snake_name,
        service_name=spec.service_name,
    )


