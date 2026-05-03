"""Top-level scaffold generator — dispatches to language-specific modules.

The entry point :func:`generate_scaffold` returns a dict of
``{relative_path: content_string}`` that the bridge endpoint can write
to disk or package into a ZIP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import shared, python_tmpl, cpp_tmpl


@dataclass
class MethodParam:
    name: str
    type: str = "string"
    required: bool = True
    description: str = ""


@dataclass
class MethodSpec:
    name: str
    params: List[MethodParam] = field(default_factory=list)
    return_type: str = "string"
    description: str = ""
    server_streaming: bool = False
    # Fully-qualified proto type names (imported protos only).
    # Empty strings = fall back to the "<Method>Request" / "<Method>Response"
    # convention used by the wizard's built-in proto generator.
    input_type: str = ""
    output_type: str = ""


@dataclass
class ServiceBlock:
    """One service inside a monorepo scaffold (single .proto, multiple
    executables sharing the same project tree)."""
    name: str
    methods: List[MethodSpec] = field(default_factory=list)


@dataclass
class ScaffoldSpec:
    """Everything the wizard collects across all steps."""

    # Step 1 — Basic info
    service_name: str = ""
    version: str = "1.0.0"
    description: str = ""
    short_desc: str = ""
    group: str = ""
    tag: str = ""

    # Step 2 — Technology
    language: str = "python"          # "python" | "cpp"
    gui_type: str = "none"            # "none" | "html" | "qml" | "wasm" | "widget"
    # Which gRPC stack the *client* uses.
    #   "google"        - Google grpc++ from MSYS2 prebuilt; server uses
    #                     the same MSYS2 toolchain.  Default.
    #   "qt"            - Client uses Qt6::Grpc + Qt6::Protobuf in a
    #                     separate qt_client/ project (Qt-installer MinGW).
    #                     Server still on MSYS2 + Google grpc.
    #   "google_vcpkg"  - Client uses Google grpc++ in qt_client_grpcpp/,
    #                     built with Qt-installer MinGW via vcpkg
    #                     (custom triplet x64-mingw-qt + ports overlay).
    #                     Server's CMakeLists is also re-targeted to vcpkg
    #                     so client AND server share one toolchain
    #                     (Qt 6.x MinGW 13.1.0 kit) end-to-end.
    client_grpc_kind: str = "google"  # "google" | "qt" | "google_vcpkg"

    # Toolchain the *server* is built with.  Independent of client choice
    # (you can mix any combination — wire format is the same).
    #   "msys2"   - Google grpc++ from MSYS2 prebuilt (default).
    #               Build via build_deploy_msys2.bat.
    #   "vcpkg"   - Google grpc++ via vcpkg + Qt-installer MinGW 13.1.0
    #               (custom triplet x64-mingw-qt + ports overlay).
    #               Build via build_qt_vcpkg.bat.
    # Picking "vcpkg" emits the same shared triplets/ + ports/ + init
    # script that the qt_client_grpcpp/ client uses, so if both sides
    # are "vcpkg" the install tree + binary cache is shared.
    server_grpc_kind: str = "msys2"  # "msys2" | "vcpkg"
    gen_nomad: bool = True
    gen_build_scripts: bool = True
    gen_readme: bool = True
    gen_stubs: bool = True
    vcpkg_root: str = ""
    protoc_path: str = ""
    grpc_plugin_path: str = ""

    # Nomad HCL configuration
    nomad_dc: str = "dc1"
    nomad_driver: str = "raw_exec"
    nomad_command: str = ""
    nomad_cpu: int = 100
    nomad_mem: int = 128
    nomad_consul_addr: str = "http://127.0.0.1:8500"

    # Step 3 — Methods
    methods: List[MethodSpec] = field(default_factory=list)

    # When the user imported a .proto file, keep its original text so we
    # write it verbatim instead of regenerating (preserves comments,
    # options, imports we couldn't parse).  Empty string = regenerate.
    proto_content_override: str = ""

    # Package name from the imported .proto's `package X;` declaration.
    # Empty string = fall back to the computed `<snake_name>.v1`.
    proto_package_override: str = ""

    # Monorepo mode: when non-empty, emit a single project folder with N
    # executables (one per service) sharing one .proto + one CMakeLists.
    # `service_name` then acts as the *project* folder name.
    services: List[ServiceBlock] = field(default_factory=list)

    # Derived helpers
    @property
    def snake_name(self) -> str:
        """CamelCase → snake_case, keeping runs of capitals together.

        ``MyService`` → ``my_service``, ``PPSService`` → ``pps_service``,
        ``XMLParser`` → ``xml_parser``.
        """
        import re
        s = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', self.service_name)
        s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
        return s.lower()

    @property
    def proto_package(self) -> str:
        return self.proto_package_override or f"{self.snake_name}.v1"

    @property
    def proto_namespace(self) -> str:
        """C++ namespace form of proto_package (dots → `::`)."""
        return self.proto_package.replace(".", "::")

    @property
    def env_prefix(self) -> str:
        return self.snake_name.upper() + "_"


def generate_scaffold(spec: ScaffoldSpec) -> Dict[str, str]:
    """Return ``{path: content}`` for every file in the scaffold.

    Paths are relative to the project root (e.g. ``src/main.cpp``).
    """
    # Monorepo path: one project folder, N executables sharing the proto.
    # v1: C++ only.  Python monorepo is a straightforward follow-up.
    if spec.services and len(spec.services) > 1:
        if spec.language != "cpp":
            raise NotImplementedError(
                "Monorepo layout is C++ only in v1. "
                "Use separate-folder layout for Python."
            )
        return cpp_tmpl.generate_monorepo(spec, spec.services)

    files: Dict[str, str] = {}

    # ---- Shared files (all combinations) --------------------------------
    # If the user imported a .proto via the wizard, write it verbatim so
    # we preserve whatever we couldn't parse (comments, options, imports).
    # Otherwise regenerate from spec.methods.
    if spec.proto_content_override:
        files[f"proto/{spec.snake_name}.proto"] = spec.proto_content_override
    else:
        files[f"proto/{spec.snake_name}.proto"] = shared.gen_proto(spec)

    if spec.gen_readme:
        files["README.md"] = shared.gen_readme(spec)

    if spec.gen_nomad:
        files[f"{spec.snake_name}.nomad.hcl"] = shared.gen_nomad(spec)

    files["service_config.json"] = shared.gen_service_config(spec)

    # ---- Language-specific files ----------------------------------------
    if spec.language == "python":
        files.update(python_tmpl.generate(spec))
    elif spec.language == "cpp":
        files.update(cpp_tmpl.generate(spec))

    # ---- Pre-generate proto stubs (optional) ----------------------------
    if spec.gen_stubs:
        stub_files = _generate_stubs(spec, files.get(f"proto/{spec.snake_name}.proto", ""))
        files.update(stub_files)

    return files


def _generate_stubs(spec: ScaffoldSpec, proto_content: str) -> Dict[str, str]:
    """Run protoc on the generated .proto and return the stub files.

    For Python: uses ``grpc_tools.protoc`` in-process — zero config.
    For C++: uses external ``protoc`` + ``grpc_cpp_plugin`` binaries.
    The user provides paths via the wizard (or they're auto-detected
    from VCPKG_ROOT).
    """
    stubs: Dict[str, str] = {}

    if not proto_content:
        return stubs

    if spec.language == "python":
        stubs.update(_generate_python_stubs(spec, proto_content))
    elif spec.language == "cpp":
        stubs.update(_generate_cpp_stubs(spec, proto_content))

    return stubs


def _generate_python_stubs(spec: ScaffoldSpec, proto_content: str) -> Dict[str, str]:
    """Use grpc_tools.protoc to compile .proto content into Python stubs."""
    import os
    import tempfile

    try:
        from grpc_tools import protoc as grpc_protoc
    except ImportError:
        # grpc_tools not installed — return empty (user will need to
        # run generate_protos.py manually).
        return {}

    stubs: Dict[str, str] = {}
    sn = spec.snake_name

    with tempfile.TemporaryDirectory() as tmpdir:
        proto_path = os.path.join(tmpdir, f"{sn}.proto")
        with open(proto_path, "w", encoding="utf-8") as f:
            f.write(proto_content)

        # Run protoc in-process
        result = grpc_protoc.main([
            "grpc_tools.protoc",
            f"--proto_path={tmpdir}",
            f"--python_out={tmpdir}",
            f"--grpc_python_out={tmpdir}",
            proto_path,
        ])

        if result != 0:
            return {}

        # Read generated files
        pb2_path = os.path.join(tmpdir, f"{sn}_pb2.py")
        grpc_path = os.path.join(tmpdir, f"{sn}_pb2_grpc.py")

        if os.path.isfile(pb2_path):
            with open(pb2_path, "r", encoding="utf-8") as f:
                stubs[f"proto/{sn}_pb2.py"] = f.read()

        if os.path.isfile(grpc_path):
            content = ""
            with open(grpc_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Patch the import to use package-relative path
            content = content.replace(
                f"import {sn}_pb2 as {sn.replace('_', '__')}__pb2",
                f"from . import {sn}_pb2 as {sn.replace('_', '__')}__pb2",
            )
            stubs[f"proto/{sn}_pb2_grpc.py"] = content

    return stubs


def _generate_cpp_stubs(spec: ScaffoldSpec, proto_content: str) -> Dict[str, str]:
    """Run ``protoc`` + ``grpc_cpp_plugin`` externally and return the
    generated ``.pb.h/.pb.cc/.grpc.pb.h/.grpc.pb.cc`` files.

    Tool paths are resolved in order:
      1. Explicit paths from the wizard (``spec.protoc_path``,
         ``spec.grpc_plugin_path``)
      2. Auto-detect from ``spec.vcpkg_root``
         (``installed/x64-*/tools/protobuf/protoc``)
      3. Fallback to bare names on PATH

    If the tools aren't found or protoc fails, returns an empty dict.
    The scaffold still works — CMake generates stubs automatically at
    build time.
    """
    import os
    import platform
    import shutil
    import subprocess
    import tempfile
    from typing import Optional as Opt

    sn = spec.snake_name

    def _find_tool(explicit: str, vcpkg_subdir: str, tool_name: str) -> Opt[str]:
        if explicit and os.path.isfile(explicit):
            return explicit
        if spec.vcpkg_root:
            triplet = "x64-windows" if platform.system() == "Windows" else "x64-linux"
            candidate = os.path.join(spec.vcpkg_root, "installed", triplet,
                                     "tools", vcpkg_subdir, tool_name)
            if platform.system() == "Windows" and not candidate.endswith(".exe"):
                candidate += ".exe"
            if os.path.isfile(candidate):
                return candidate
        return shutil.which(tool_name)

    protoc = _find_tool(spec.protoc_path, "protobuf", "protoc")
    grpc_plugin = _find_tool(spec.grpc_plugin_path, "grpc", "grpc_cpp_plugin")

    if not protoc:
        return {}

    stubs: Dict[str, str] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        proto_path = os.path.join(tmpdir, f"{sn}.proto")
        with open(proto_path, "w", encoding="utf-8") as f:
            f.write(proto_content)

        gen_dir = os.path.join(tmpdir, "gen")
        os.makedirs(gen_dir)

        cmd = [
            protoc,
            f"--proto_path={tmpdir}",
            f"--cpp_out={gen_dir}",
        ]
        if grpc_plugin:
            cmd += [
                f"--grpc_out={gen_dir}",
                f"--plugin=protoc-gen-grpc={grpc_plugin}",
            ]
        cmd.append(proto_path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception:
            return {}

        if result.returncode != 0:
            return {}

        for filename, out_path in [
            (f"{sn}.pb.h",       f"gen/{sn}.pb.h"),
            (f"{sn}.pb.cc",      f"gen/{sn}.pb.cc"),
            (f"{sn}.grpc.pb.h",  f"gen/{sn}.grpc.pb.h"),
            (f"{sn}.grpc.pb.cc", f"gen/{sn}.grpc.pb.cc"),
        ]:
            full = os.path.join(gen_dir, filename)
            if os.path.isfile(full):
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    stubs[out_path] = fh.read()

    return stubs
