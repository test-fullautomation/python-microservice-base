"""Shared scaffold generators used by both Python and C++ templates.

Produces:
- .proto file
- service_config.json
- Nomad .nomad.hcl job spec
- README.md
"""

from __future__ import annotations

import datetime as _dt
import getpass as _getpass
import json
import os as _os
import sys as _sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .generator import ScaffoldSpec, MethodSpec


# -----------------------------------------------------------------------
# Generation-time metadata (used in file headers)
# -----------------------------------------------------------------------

def _full_username() -> str:
    """
Best-effort full display name of the current OS user.

Tries (in order):

1. Windows: ``GetUserNameExW`` (NameDisplay) via ctypes — returns the
   AD / local account display name (e.g. "Cuong Nguyen Huynh Tri").
2. Windows fallback: parse ``net user <login>`` for the ``Full Name``
   line.
3. Linux: ``pwd.getpwuid().pw_gecos`` — the GECOS first-name field.
4. Final fallback: ``getpass.getuser()`` (the bare login name).

**Returns:**

* ``name``

  / *Type*: str /

  Full display name when available, login name otherwise.
    """
    if _sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(256)
            size = ctypes.c_uint(256)
            # NameDisplay = 3 (EXTENDED_NAME_FORMAT)
            if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)):
                if buf.value:
                    return buf.value
        except Exception:
            pass
        try:
            import subprocess
            out = subprocess.run(
                ["net", "user", _getpass.getuser()],
                capture_output=True, text=True, timeout=2,
            )
            for line in out.stdout.splitlines():
                if line.lower().startswith("full name"):
                    parts = line.split(None, 2)
                    if len(parts) >= 3:
                        full = parts[2].strip()
                        if full:
                            return full
        except Exception:
            pass
    else:
        try:
            import pwd  # type: ignore[import-not-found]
            entry = pwd.getpwuid(_os.getuid())
            gecos = (entry.pw_gecos or "").split(",")[0].strip()
            if gecos:
                return gecos
        except Exception:
            pass
    return _getpass.getuser()


def _today_dotted() -> str:
    """Return today's date in ``DD.MM.YYYY`` (history-line format)."""
    return _dt.date.today().strftime("%d.%m.%Y")


def _today_long() -> str:
    """Return today's date in ``Mon YYYY`` (header "Initially created" format)."""
    return _dt.date.today().strftime("%b %Y")


def python_file_header(filename: str, description: str,
                       version: str = "1.0.0") -> str:
    """
Render the standard QConnect-style Python file header block.

Format mirrors the upstream QConnectBase convention:

  - Apache 2.0 boilerplate
  - File / Author / Date / Description / History sections
  - Author taken from :func:`_full_username` (full PC user name)
  - Date and history entry generated from today's date

**Arguments:**

* ``filename``

  / *Condition*: required / *Type*: str /

  Bare filename (no path), e.g. ``"main.py"``.

* ``description``

  / *Condition*: required / *Type*: str /

  One-paragraph description of what the module provides.  May contain
  newlines; will be re-indented to fit the comment column.

* ``version``

  / *Condition*: optional / *Type*: str / *Default*: "1.0.0" /

  Initial version string written in the History entry.

**Returns:**

* ``header``

  / *Type*: str /

  Multi-line ``#``-comment header, ending with a blank line for clean
  separation from the module docstring that follows.
    """
    author = _full_username()
    today = _today_dotted()
    year = _dt.date.today().year
    long_date = _today_long()

    desc_lines = "\n".join(
        f"#   {line}" if line else "#"
        for line in description.strip().splitlines()
    )

    return (
        f"#  Copyright 2020-{year} Robert Bosch GmbH\n"
        f"#\n"
        f"#  Licensed under the Apache License, Version 2.0 (the \"License\");\n"
        f"#  you may not use this file except in compliance with the License.\n"
        f"#  You may obtain a copy of the License at\n"
        f"#\n"
        f"#      http://www.apache.org/licenses/LICENSE-2.0\n"
        f"#\n"
        f"#  Unless required by applicable law or agreed to in writing, software\n"
        f"#  distributed under the License is distributed on an \"AS IS\" BASIS,\n"
        f"#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n"
        f"#  See the License for the specific language governing permissions and\n"
        f"#  limitations under the License.\n"
        f"# *******************************************************************************\n"
        f"#\n"
        f"# File: {filename}\n"
        f"#\n"
        f"# Initially created by {author} / {long_date}.\n"
        f"#\n"
        f"# Description:\n"
        f"{desc_lines}\n"
        f"#\n"
        f"# History:\n"
        f"#\n"
        f"# {today} / V {version} / {author}\n"
        f"# - Initialize\n"
        f"#\n"
        f"# *******************************************************************************\n"
    )


def cpp_file_header(filename: str, description: str,
                    version: str = "1.0.0") -> str:
    """
Render the QConnect-style file header as a C/C++ ``//`` comment block.

Same content as :func:`python_file_header` but with ``//`` line
comments so it compiles inside a ``.h`` / ``.cpp`` source file.

**Arguments:**

* ``filename``

  / *Condition*: required / *Type*: str /

  Bare filename, e.g. ``"main.cpp"`` or ``"HelloService.h"``.

* ``description``

  / *Condition*: required / *Type*: str /

  Module / file description.  Multi-line allowed.

* ``version``

  / *Condition*: optional / *Type*: str / *Default*: "1.0.0" /

  Initial version string.

**Returns:**

* ``header``

  / *Type*: str /

  Multi-line ``//``-comment header, ending with a blank line.
    """
    author = _full_username()
    today = _today_dotted()
    year = _dt.date.today().year
    long_date = _today_long()

    desc_lines = "\n".join(
        f"//   {line}" if line else "//"
        for line in description.strip().splitlines()
    )

    return (
        f"//  Copyright 2020-{year} Robert Bosch GmbH\n"
        f"//\n"
        f"//  Licensed under the Apache License, Version 2.0 (the \"License\");\n"
        f"//  you may not use this file except in compliance with the License.\n"
        f"//  You may obtain a copy of the License at\n"
        f"//\n"
        f"//      http://www.apache.org/licenses/LICENSE-2.0\n"
        f"//\n"
        f"//  Unless required by applicable law or agreed to in writing, software\n"
        f"//  distributed under the License is distributed on an \"AS IS\" BASIS,\n"
        f"//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.\n"
        f"//  See the License for the specific language governing permissions and\n"
        f"//  limitations under the License.\n"
        f"// *******************************************************************************\n"
        f"//\n"
        f"// File: {filename}\n"
        f"//\n"
        f"// Initially created by {author} / {long_date}.\n"
        f"//\n"
        f"// Description:\n"
        f"{desc_lines}\n"
        f"//\n"
        f"// History:\n"
        f"//\n"
        f"// {today} / V {version} / {author}\n"
        f"// - Initialize\n"
        f"//\n"
        f"// *******************************************************************************\n"
    )


# -----------------------------------------------------------------------
# Proto
# -----------------------------------------------------------------------

_PROTO_TYPE_MAP = {
    "string": "string",
    "str": "string",
    "int": "int32",
    "int32": "int32",
    "int64": "int64",
    "float": "float",
    "double": "double",
    "bool": "bool",
    "bytes": "bytes",
    "dict": "string",
    "list": "string",
}


def _proto_type(t: str) -> str:
    """
Map a wizard / config type name to its proto3 wire type.

**Arguments:**

* ``t``

  / *Condition*: required / *Type*: str /

  Type name as accepted in the wizard / scaffold spec
  (e.g. ``"string"``, ``"int"``, ``"bool"``).

**Returns:**

* ``proto_type``

  / *Type*: str /

  Proto3 type (e.g. ``"string"``, ``"int32"``).  Unknown types fall
  back to ``"string"``.
    """
    return _PROTO_TYPE_MAP.get(t.lower(), "string")


def gen_proto(spec: "ScaffoldSpec") -> str:
    """
Render the ``.proto`` file for a single service.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification (service name, methods, package, …).

**Returns:**

* ``proto``

  / *Type*: str /

  The full ``.proto`` text, including the service block and one
  request/response message per method.
    """
    lines = [
        f'syntax = "proto3";',
        f"",
        f"package {spec.proto_package};",
        f"",
        f"service {spec.service_name}Service {{",
    ]

    for m in spec.methods:
        stream = "stream " if m.server_streaming else ""
        lines.append(
            f"  rpc {m.name} ({m.name}Request) "
            f"returns ({stream}{m.name}Response);"
        )

    lines.append("}")
    lines.append("")

    # Message definitions
    for m in spec.methods:
        # Request
        lines.append(f"message {m.name}Request {{")
        for i, p in enumerate(m.params, 1):
            lines.append(f"  {_proto_type(p.type)} {p.name} = {i};")
        if not m.params:
            lines.append("  // no parameters")
        lines.append("}")
        lines.append("")

        # Response
        lines.append(f"message {m.name}Response {{")
        lines.append(f"  {_proto_type(m.return_type)} result = 1;")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


# -----------------------------------------------------------------------
# service_config.json
# -----------------------------------------------------------------------

def gen_service_config(spec: "ScaffoldSpec") -> str:
    """
Render the ``service_config.json`` metadata file for a service.

The shape carries broker-era fields (``broker_*``) for back-compat
with the legacy Manager GUI's service-info reader.  New gRPC-only
deployments ignore those fields.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification.

**Returns:**

* ``json_text``

  / *Type*: str /

  Pretty-printed JSON document (4-space indent, trailing newline).
    """
    cfg = {
        "name": spec.service_name,
        "version": spec.version,
        "routing_key": spec.service_name,
        "description": spec.description or f"{spec.service_name} microservice.",
        "shortdesc": spec.short_desc or spec.service_name,
        "group": spec.group or "Services",
        "tag": spec.tag or "",
        "gui_support": spec.gui_type != "none",
        "downloadable": False,
        "broker_host": "localhost",
        "broker_port": 5672,
        "broker_vhost": "/",
        "broker_user": "guest",
        "broker_pass": "guest",
    }
    return json.dumps(cfg, indent=4) + "\n"


# -----------------------------------------------------------------------
# Nomad job spec
# -----------------------------------------------------------------------

def gen_nomad(spec: "ScaffoldSpec") -> str:
    """
Render the ``<service>.nomad.hcl`` job spec.

Wires the dynamic ``NOMAD_PORT_grpc`` allocation into ``<PREFIX>_GRPC_PORT``
and ``<PREFIX>_ADVERTISE_ADDR`` env vars; sets ``<PREFIX>_CONSUL_ADDR``
to the configured Consul address so ``ServiceRunner`` can register the
gRPC port automatically.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification.  Reads ``nomad_dc``, ``nomad_driver``,
  ``nomad_cpu``, ``nomad_mem``, ``nomad_consul_addr`` if present.

**Returns:**

* ``hcl``

  / *Type*: str /

  Nomad HCL job definition, ready to ``nomad job run``.
    """
    sn = spec.snake_name
    prefix = spec.env_prefix
    dc = getattr(spec, 'nomad_dc', 'dc1') or 'dc1'
    driver = getattr(spec, 'nomad_driver', 'raw_exec') or 'raw_exec'
    cpu = getattr(spec, 'nomad_cpu', 100) or 100
    mem = getattr(spec, 'nomad_mem', 128) or 128

    # Command
    user_cmd = getattr(spec, 'nomad_command', '') or ''
    if user_cmd:
        cmd_line = f'        command = "{user_cmd}"'
    elif spec.language == "python":
        cmd_line = (
            '        command = "python"\n'
            f'        args    = ["/path/to/{sn}/main.py"]'
        )
    else:
        cmd_line = f'        command = "/path/to/{sn}"'

    # Env vars
    env_lines = ""
    if spec.language == "python":
        env_lines += f'        PYTHONPATH = "/path/to/{sn}"\n\n'
    consul_addr = getattr(spec, 'nomad_consul_addr', '') or 'http://127.0.0.1:8500'
    env_lines += (
        f'        {prefix}GRPC_PORT      = "${{NOMAD_PORT_grpc}}"\n'
        f'        {prefix}ADVERTISE_ADDR = "127.0.0.1"\n'
        f'        {prefix}CONSUL_ADDR    = "{consul_addr}"\n'
        f'        {prefix}LOG_LEVEL      = "INFO"\n'
    )

    return (
        f'# Nomad job spec for {spec.service_name}.\n'
        f'#\n'
        f'# Submit from the GUI:  Service Network > Nomad > Submit Job\n'
        f'# Or from the CLI:     nomad job run {sn}.nomad.hcl\n'
        f'#\n'
        f'# Fields:\n'
        f'#   datacenters  — which Nomad datacenter(s) can run this job\n'
        f'#   driver       — raw_exec: direct process, no isolation\n'
        f'#                  exec: chroot isolation (Linux only)\n'
        f'#                  docker: container-based\n'
        f'#   port "grpc"  — dynamic port; Nomad picks a free one and\n'
        f'#                  injects it as NOMAD_PORT_grpc\n'
        f'#   resources    — cpu (MHz) and memory (MB) limits\n'
        f'\n'
        f'job "{sn}" {{\n'
        f'  datacenters = ["{dc}"]\n'
        f'  type        = "service"\n'
        f'\n'
        f'  group "{sn}" {{\n'
        f'    count = 1\n'
        f'\n'
        f'    network {{\n'
        f'      port "grpc" {{}}  # dynamic port allocation\n'
        f'    }}\n'
        f'\n'
        f'    task "server" {{\n'
        f'      driver = "{driver}"\n'
        f'\n'
        f'      config {{\n'
        f'{cmd_line}\n'
        f'      }}\n'
        f'\n'
        f'      env {{\n'
        f'{env_lines}'
        f'      }}\n'
        f'\n'
        f'      resources {{\n'
        f'        cpu    = {cpu}   # MHz\n'
        f'        memory = {mem}   # MB\n'
        f'      }}\n'
        f'    }}\n'
        f'  }}\n'
        f'}}\n'
    )


# -----------------------------------------------------------------------
# README.md
# -----------------------------------------------------------------------

def gen_readme(spec: "ScaffoldSpec") -> str:
    """
Render the ``README.md`` for a generated service.

Output covers: project layout, build instructions for the language /
GUI / toolchain combination the wizard picked, run instructions
(direct + Nomad), and the list of RPC methods exposed by the service.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification.

**Returns:**

* ``markdown``

  / *Type*: str /

  README contents (Markdown).
    """
    sn = spec.snake_name
    lang_label = "Python" if spec.language == "python" else "C++"
    gui_label = {
        "none": "no GUI",
        "html": "HTML/JS GUI",
        "qml": "QML GUI",
        "wasm": "Qt WASM GUI",
        "widget": "Qt Widgets GUI",
    }.get(spec.gui_type, "")

    methods_doc = ""
    for m in spec.methods:
        params = ", ".join(
            f"`{p.name}` ({p.type})" for p in m.params
        ) or "(none)"
        streaming = " (server streaming)" if m.server_streaming else ""
        methods_doc += f"- **{m.name}**{streaming} — params: {params} → `{m.return_type}`\n"

    if spec.language == "python":
        run_block = (
            f"### Run\n\n"
            f"```bash\n"
            f"# Generate proto stubs (one time)\n"
            f"python scripts/generate_protos.py\n\n"
            f"# Start the service\n"
            f"python main.py\n"
            f"```\n"
        )
    else:
        run_block = (
            f"### Build\n\n"
            f"```bash\n"
            f"mkdir build && cd build\n"
            f"cmake -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake ..\n"
            f"cmake --build . --config Release\n"
            f"```\n\n"
            f"### Run\n\n"
            f"```bash\n"
            f"export {spec.env_prefix}CONSUL_ADDR=http://127.0.0.1:8500\n"
            f"./{sn}\n"
            f"```\n"
        )

    if spec.language == "python":
        framework_dep = (
            "- **MicroserviceBase Python package** — provides `ServiceRunner`, "
            "`ServicerEntry`, Consul/Nomad adapters.  Install from the framework "
            "checkout (not on PyPI):\n\n"
            "  ```cmd\n"
            "  git clone -b ugc1hc/feat/migrate_to_ta_architecture ^\n"
            "      https://github.com/test-fullautomation/python-microservice-base.git\n"
            "  cd python-microservice-base\n"
            '  "%RobotPythonPath%\\python" -m pip install --no-deps --no-build-isolation .\n'
            "  ```\n"
        )
    else:
        framework_dep = (
            "- **MicroserviceBase C++ runtime** — provides `ServiceRunner`, "
            "`ServiceClient`, Consul registration.  `CMakeLists.txt` calls "
            "`find_package(MicroserviceBase CONFIG)`; if it isn't installed, "
            "clone the framework alongside this scaffold so the in-tree "
            "fallback resolves:\n\n"
            "  ```cmd\n"
            "  git clone -b ugc1hc/feat/migrate_to_ta_architecture ^\n"
            "      https://github.com/test-fullautomation/python-microservice-base.git\n"
            "  ```\n\n"
            "  Other install paths (CMake `--install` prefix, vcpkg "
            "overlay-port) are documented in the framework's "
            "`docs/runtime_cpp_install.md`.\n"
            "- **vcpkg toolchain** with `grpc`, `protobuf`, `curl` (or system "
            "equivalents).\n"
        )

    qtc_troubleshooting = ""
    if spec.language != "python":
        qtc_troubleshooting = (
            "\n## Troubleshooting\n\n"
            "### Qt Creator: *The ABI of the selected debugger does not "
            "match the toolchain ABI*\n\n"
            "CMakePresets pins the compiler but has no field for a "
            "debugger, so Qt Creator's auto-imported preset kit pairs "
            "the MinGW compiler with whatever debugger it auto-detects "
            "(often MSVC `cdb.exe` or a system `gdb` with a different "
            "ABI).\n\n"
            "**One-time fix** (per machine, not per project):\n\n"
            "1. *Edit → Preferences → Kits → Debuggers* — "
            "verify there's an entry for "
            "`C:\\Qt\\Tools\\mingw1310_64\\bin\\gdb.exe`.  If not: *Add* "
            "→ *Path* = that path, *Name* = `MinGW gdb (Qt 6.11)`.  "
            "*Apply*.\n"
            "2. *Kits* tab → select the auto-imported preset kit "
            "(e.g. `vcpkg + Qt MinGW 13.1.0 (Release)`) → set "
            "*Debugger* to the entry from step 1.  *Apply* + *OK*.\n\n"
            "The fix sticks across project re-imports because Qt Creator "
            "stores it in the kit, not the preset.\n"
        )

    sn = spec.snake_name
    is_cpp = spec.language == "cpp"

    if is_cpp:
        folder_block = (
            "## Folder structure\n\n"
            "`[edit]` marks files where you write business logic.  "
            "Everything else is scaffolding regenerated by `mb-scaffold`.\n\n"
            "```\n"
            f"{spec.service_name}/\n"
            f"├── proto/{sn}.proto         # API definition (gRPC service + messages)\n"
            f"├── src/\n"
            f"│   ├── main.cpp              # ServiceRunner entry-point\n"
            f"│   ├── Settings.h            # config (env prefix {spec.env_prefix})\n"
            f"│   ├── domain/               # [edit] business logic (pure C++)\n"
            f"│   └── adapters/api/         # [edit] proto<->domain wrapper\n"
            f"├── deploy/{sn}.nomad.hcl  # Nomad job (one .exe, dynamic port)\n"
            f"├── client/                   # console gRPC client subproject\n"
            f"├── CMakeLists.txt            # one add_executable + proto codegen\n"
            f"├── build_deploy.bat / .sh    # one-shot build\n"
            f"├── set_env*.bat / .sh        # toolchain env (VCPKG_ROOT, QT_DIR, ...)\n"
            f"└── README.md\n"
            "```\n\n"
        )
        flow_block = (
            "## Build & run flow\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "    Start([Start])\n"
            "    Setup[\"1\\. One-time setup<br/>setx VCPKG_ROOT, QT_DIR, QT_MINGW_BIN\"]\n"
            "    Choose{\"Toolchain?\"}\n"
            "    Prebuilt{\"Have prebuilt zip?\"}\n"
            "    Import[\"import_prebuilt.bat &lt;zip&gt;<br/>~30 seconds\"]\n"
            "    BuildVcpkg[\"build_qt_vcpkg.bat<br/>(or Qt Creator F5)\"]\n"
            "    BuildMSYS2[\"build_deploy_msys2.bat\"]\n"
            f"    BuildResult[\"build*/{sn}.exe<br/>+ runtime DLLs alongside\"]\n"
            f"    LocalRun[\"Run locally:<br/>./{sn}.exe\"]\n"
            "    Pkg[\"deploy_qt_vcpkg.bat<br/>→ dist-qt-vcpkg/\"]\n"
            f"    NomadRun[\"nomad job run<br/>deploy/{sn}.nomad.hcl\"]\n"
            f"    Discover[\"Clients discover via Consul<br/>(svc name: {sn})\"]\n"
            "\n"
            "    Start --> Setup --> Choose\n"
            "    Choose -->|\"Qt MinGW + vcpkg<br/>(recommended)\"| Prebuilt\n"
            "    Choose -->|MSYS2| BuildMSYS2 --> BuildResult\n"
            "    Prebuilt -->|\"Yes (~2 min total)\"| Import --> BuildVcpkg\n"
            "    Prebuilt -->|\"No (first build ~30-60 min)\"| BuildVcpkg\n"
            "    BuildVcpkg --> BuildResult\n"
            "    BuildResult --> LocalRun\n"
            "    BuildResult -->|For sharing| Pkg\n"
            "    LocalRun --> NomadRun\n"
            "    Pkg --> NomadRun\n"
            "    NomadRun --> Discover\n"
            "```\n\n"
        )
    else:
        # Python services have a much simpler flow -- no vcpkg, no MinGW.
        folder_block = (
            "## Folder structure\n\n"
            "```\n"
            f"{spec.service_name}/\n"
            f"├── proto/{sn}.proto         # API definition\n"
            f"├── main.py                   # ServiceRunner entry-point\n"
            f"├── domain/                   # [edit] business logic\n"
            f"├── adapters/api/             # [edit] proto<->domain wrapper\n"
            f"├── deploy/{sn}.nomad.hcl  # Nomad job\n"
            f"├── pyproject.toml\n"
            f"└── README.md\n"
            "```\n\n"
        )
        flow_block = (
            "## Build & run flow\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "    Start([Start])\n"
            "    Install[\"pip install -e .\"]\n"
            "    GenStubs[\"python scripts/generate_protos.py<br/>(one-time)\"]\n"
            f"    Run[\"python main.py<br/>or {sn} (entry-point)\"]\n"
            f"    Nomad[\"nomad job run deploy/{sn}.nomad.hcl\"]\n"
            f"    Discover[\"Clients discover via Consul (svc: {sn})\"]\n"
            "\n"
            "    Start --> Install --> GenStubs --> Run --> Nomad --> Discover\n"
            "```\n\n"
        )

    return (
        f"# {spec.service_name}\n\n"
        f"{spec.description or spec.service_name + ' microservice.'}\n\n"
        f"- **Language:** {lang_label}\n"
        f"- **GUI:** {gui_label}\n"
        f"- **Version:** {spec.version}\n"
        f"- **Group:** {spec.group or 'Services'}\n\n"
        f"## Methods\n\n"
        f"{methods_doc}\n"
        f"{folder_block}"
        f"{flow_block}"
        f"## Prerequisites\n\n"
        f"- Consul agent running on `{spec.env_prefix}CONSUL_ADDR` "
        f"(default `http://127.0.0.1:8500`).\n"
        f"{framework_dep}\n"
        f"{run_block}\n"
        f"## Verify\n\n"
        f"```bash\n"
        f"grpcurl -plaintext <host>:<port> list\n"
        f"```\n"
        f"{qtc_troubleshooting}"
    )
