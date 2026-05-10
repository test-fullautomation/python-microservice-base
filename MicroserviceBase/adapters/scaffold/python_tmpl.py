"""Python service scaffold templates.

Generates the full project structure for a Python gRPC microservice
using the MicroserviceBase async runtime (ServiceRunner + Consul).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from .shared import python_file_header

if TYPE_CHECKING:
    from .generator import ScaffoldSpec


def generate(spec: "ScaffoldSpec") -> Dict[str, str]:
    """
Render every file for a Python single-service gRPC scaffold.

Produces ``main.py``, ``config.py`` (Pydantic ``BaseServiceSettings``
subclass), ``context.py`` (composition root), ``pyproject.toml``,
domain stubs, gRPC adapter, proto-stub generator script, and
optionally HTML/JS GUI files when ``spec.gui_type == "html"``.

For multi-service / monorepo layouts use :func:`generate_monorepo`.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification.

**Returns:**

* ``files``

  / *Type*: Dict[str, str] /

  Map of relative-path → file-contents for every file the scaffold
  should write.
    """
    files: Dict[str, str] = {}

    sn = spec.snake_name
    prefix = spec.env_prefix
    svc = spec.service_name

    files["main.py"] = _main_py(spec)
    files["config.py"] = _config_py(spec)
    files["context.py"] = _context_py(spec)
    files["pyproject.toml"] = _pyproject(spec)
    files["domain/__init__.py"] = ""
    files[f"domain/{sn}_service.py"] = _domain_service(spec)
    files["adapters/__init__.py"] = ""
    files["adapters/api/__init__.py"] = ""
    files["adapters/api/grpc_adapter.py"] = _grpc_adapter(spec)
    files["proto/__init__.py"] = ""
    files["scripts/generate_protos.py"] = _gen_protos_script(spec)

    if spec.gui_type == "html":
        files[f"GUIs/{svc}.html"] = _gui_html(spec)
        files[f"GUIs/{svc}.js"] = _gui_js(spec)

    return files


# -----------------------------------------------------------------------
# main.py
# -----------------------------------------------------------------------

def _main_py(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    header = python_file_header(
        "main.py",
        f"Entry point for the {svc} service.\n"
        f"Composes the dependency-injection context and hands it off to\n"
        f"ServiceRunner, which manages the gRPC server lifecycle and\n"
        f"Consul registration.",
    )
    return f'''{header}\
"""
Entry point for {svc}.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from context import create_context
from proto import {sn}_pb2, {sn}_pb2_grpc  # type: ignore[import-not-found]

from MicroserviceBase.runtime import ServiceRunner, ServicerEntry


async def amain() -> None:
    """
Async entry point.  Builds the service context, configures logging,
wires the gRPC servicer into a ServiceRunner, and serves until a
shutdown signal arrives.

**Returns:**

(*no returns*)
    """
    ctx = create_context()

    logging.basicConfig(
        level=ctx.settings.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    full_service_name = {sn}_pb2.DESCRIPTOR.services_by_name[
        "{svc}Service"
    ].full_name

    runner = ServiceRunner(
        servicers=[
            ServicerEntry(
                register_fn={sn}_pb2_grpc.add_{svc}ServiceServicer_to_server,
                full_service_name=full_service_name,
                servicer=ctx.grpc_adapter,
            )
        ],
        settings=ctx.settings,
        tags=["v1"],
    )
    await runner.serve_forever()


if __name__ == "__main__":
    asyncio.run(amain())
'''


# -----------------------------------------------------------------------
# config.py
# -----------------------------------------------------------------------

def _config_py(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    prefix = spec.env_prefix
    header = python_file_header(
        "config.py",
        f"Pydantic settings for the {spec.service_name} service.\n"
        f"All fields are loaded from environment variables prefixed with\n"
        f"`{prefix}` (e.g. {prefix}GRPC_PORT, {prefix}CONSUL_ADDR).",
    )
    return f'''{header}\
"""
Settings for {spec.service_name}.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from MicroserviceBase.runtime import BaseServiceSettings


class Settings(BaseServiceSettings):
    """
Settings for the {spec.service_name} service.

Inherits the standard fields from :class:`BaseServiceSettings`
(``service_host``, ``grpc_port``, ``advertise_addr``, ``consul_addr``,
``consul_token``, ``log_level``).  Add service-specific fields here as
plain class attributes — Pydantic will read them from env vars prefixed
with ``{prefix}``.

**Attributes:**

* ``service_name``

  / *Type*: str / *Default*: "{sn}" /

  Logical service name used for Consul registration.  Override via
  ``{prefix}SERVICE_NAME`` if running multiple instances of this
  service on the same Consul cluster.
    """
    model_config = SettingsConfigDict(
        env_prefix="{prefix}",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "{sn}"
'''


# -----------------------------------------------------------------------
# context.py
# -----------------------------------------------------------------------

def _context_py(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    cls = f"{svc}Service"
    header = python_file_header(
        "context.py",
        f"Dependency-injection composition root for the {svc} service.\n"
        f"Wires Settings, the domain class, and the gRPC adapter together.\n"
        f"main.py calls create_context() once at startup.",
    )
    return f'''{header}\
"""
Dependency injection for {svc}.
"""

from __future__ import annotations

from dataclasses import dataclass

from adapters.api.grpc_adapter import {svc}GrpcAdapter
from config import Settings
from domain.{sn}_service import {cls}


@dataclass
class Context:
    """
Bag of constructed objects passed around the service.

**Attributes:**

* ``settings``

  / *Type*: Settings /

  Service settings loaded from environment.

* ``domain``

  / *Type*: {cls} /

  The pure-business-logic domain instance.

* ``grpc_adapter``

  / *Type*: {svc}GrpcAdapter /

  gRPC inbound adapter that translates protobuf calls to ``domain``
  method invocations.
    """
    settings: Settings
    domain: {cls}
    grpc_adapter: {svc}GrpcAdapter


def create_context() -> Context:
    """
Build the service context.

**Returns:**

* ``ctx``

  / *Type*: Context /

  Fully-wired :class:`Context` ready to hand to ServiceRunner.
    """
    settings = Settings()
    domain = {cls}()
    grpc_adapter = {svc}GrpcAdapter(domain)
    return Context(settings=settings, domain=domain, grpc_adapter=grpc_adapter)
'''


# -----------------------------------------------------------------------
# domain/<snake>_service.py
# -----------------------------------------------------------------------

def _domain_service(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    cls = f"{svc}Service"

    def _arg_block(p) -> str:
        return (
            f"\n* ``{p.name}``\n"
            f"\n  / *Condition*: required / *Type*: str /\n"
            f"\n  TODO: describe ``{p.name}``.\n"
        )

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"{p.name}: str" for p in m.params)
        if params:
            params = ", " + params

        arg_section = ""
        if m.params:
            arg_section = "\n**Arguments:**\n" + "".join(_arg_block(p) for p in m.params)

        if m.server_streaming:
            methods += f'''
    async def {_snake(m.name)}(self{params}):
        """
{m.name} — TODO: describe what this server-streaming RPC does.
{arg_section}
**Yields:**

* ``event``

  / *Type*: dict /

  TODO: describe each event yielded to the caller.  The default stub
  yields a placeholder dict ``{{"result": "not implemented"}}`` once
  and stops.
        """
        # TODO: replace with real streaming logic.  Each yielded value
        # becomes one streaming event delivered to the gRPC client.
        yield {{"result": "not implemented"}}
'''
        else:
            methods += f'''
    async def {_snake(m.name)}(self{params}) -> str:
        """
{m.name} — TODO: describe what this RPC does.
{arg_section}
**Returns:**

* ``result``

  / *Type*: str /

  TODO: describe the return value.  The default stub returns the
  literal string ``"not implemented"``.
        """
        # TODO: replace with real implementation.
        return "not implemented"
'''

    header = python_file_header(
        f"{_snake(svc)}_service.py",
        f"Pure business logic for the {svc} service.\n"
        f"This module owns the domain model and contains zero I/O — no\n"
        f"gRPC, no Consul, no Nomad, no HTTP.  All inbound traffic enters\n"
        f"through the gRPC adapter (adapters/api/grpc_adapter.py) and is\n"
        f"translated into method calls on this class.",
    )

    return f'''{header}\
"""
Pure business logic for {svc} — no gRPC, no I/O.
"""

from __future__ import annotations

from typing import AsyncIterator


class {cls}:
    """
Domain service for {svc}.

One method per RPC defined in the .proto file.  Edit the bodies to
plug in real logic.  Method signatures should stay aligned with the
proto so the gRPC adapter can call them without translation glue.
    """
{methods if methods else "    pass"}
'''


# -----------------------------------------------------------------------
# adapters/api/grpc_adapter.py
# -----------------------------------------------------------------------

def _grpc_adapter(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    cls = f"{svc}Service"

    imports = (
        f"from proto import {sn}_pb2, {sn}_pb2_grpc  "
        f"# type: ignore[import-not-found]\n"
        f"from domain.{sn}_service import {cls}\n"
    )

    def _request_field_block(p) -> str:
        return (
            f"\n  Field ``{p.name}`` is forwarded to the domain layer.\n"
        )

    methods = ""
    for m in spec.methods:
        param_reads = "\n".join(
            f"        _{p.name} = request.{p.name}"
            for p in m.params
        )
        args = ", ".join(f"_{p.name}" for p in m.params)

        request_doc = f"Proto message ``{m.name}Request``."
        if m.params:
            request_doc += "  Fields: " + ", ".join(f"``{p.name}``" for p in m.params) + "."

        if m.server_streaming:
            methods += f'''
    async def {m.name}(self, request, context):
        """
Handle a server-streaming {m.name} RPC.

**Arguments:**

* ``request``

  / *Condition*: required / *Type*: {m.name}Request /

  {request_doc}

* ``context``

  / *Condition*: required / *Type*: grpc.aio.ServicerContext /

  Per-call context (deadline, metadata, abort, …).

**Yields:**

* ``response``

  / *Type*: {m.name}Response /

  One proto message per event produced by the domain.
        """
{param_reads or "        pass"}
        async for item in self._domain.{_snake(m.name)}({args}):
            yield {sn}_pb2.{m.name}Response(result=str(item.get("result", "")))
'''
        else:
            methods += f'''
    async def {m.name}(self, request, context):
        """
Handle a unary {m.name} RPC.

**Arguments:**

* ``request``

  / *Condition*: required / *Type*: {m.name}Request /

  {request_doc}

* ``context``

  / *Condition*: required / *Type*: grpc.aio.ServicerContext /

  Per-call context (deadline, metadata, abort, …).

**Returns:**

* ``response``

  / *Type*: {m.name}Response /

  Proto response message with field ``result``.
        """
{param_reads or "        pass"}
        result = await self._domain.{_snake(m.name)}({args})
        return {sn}_pb2.{m.name}Response(result=str(result))
'''

    header = python_file_header(
        "grpc_adapter.py",
        f"gRPC inbound adapter for {cls}.\n"
        f"Translates protobuf request/response messages into method calls\n"
        f"on the domain service.  One method per RPC.  Do not change the\n"
        f"signatures (they are required by the proto-generated servicer\n"
        f"base class); edit only the body to plug in real logic.",
    )

    return f'''{header}\
"""
gRPC inbound adapter for {cls}.
"""

from __future__ import annotations

import grpc

{imports}

class {svc}GrpcAdapter({sn}_pb2_grpc.{svc}ServiceServicer):
    """
gRPC servicer that bridges proto messages and the domain class.
    """

    def __init__(self, domain: {cls}) -> None:
        """
Wire the adapter to the domain service.

**Arguments:**

* ``domain``

  / *Condition*: required / *Type*: {cls} /

  Pure-business-logic instance.  Held by reference; method calls go
  straight through.
        """
        self._domain = domain
{methods}
'''


# -----------------------------------------------------------------------
# scripts/generate_protos.py
# -----------------------------------------------------------------------

def _gen_protos_script(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    header = python_file_header(
        "generate_protos.py",
        f"Helper script that runs `protoc` on {sn}.proto and patches the\n"
        f"generated `_pb2_grpc.py` to use a package-relative import.\n"
        f"Run from the service root:  python scripts/generate_protos.py",
    )
    return f'''#!/usr/bin/env python3
{header}\
"""
Generate Python gRPC stubs from {sn}.proto.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
PROTO_DIR = SERVICE_ROOT / "proto"


def main() -> int:
    """
Run grpc_tools.protoc on the service's .proto file.

Patches the generated ``_pb2_grpc.py`` so its import of the matching
``_pb2`` module uses a package-relative path — needed because the
service runs the ``proto/`` directory as a package, not as a top-level
import root.

**Returns:**

* ``exit_code``

  / *Type*: int /

  ``0`` on success.  Forwards protoc's non-zero exit code on failure;
  ``1`` when the .proto file is missing.
    """
    proto_file = PROTO_DIR / "{sn}.proto"
    if not proto_file.exists():
        print(f"ERROR: {{proto_file}} not found", file=sys.stderr)
        return 1

    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"-I{{PROTO_DIR}}",
        f"--python_out={{PROTO_DIR}}",
        f"--grpc_python_out={{PROTO_DIR}}",
        str(proto_file),
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return result.returncode

    grpc_stub = PROTO_DIR / "{sn}_pb2_grpc.py"
    if grpc_stub.exists():
        text = grpc_stub.read_text(encoding="utf-8")
        patched = text.replace(
            "import {sn}_pb2 as {sn.replace("_", "__")}__pb2",
            "from . import {sn}_pb2 as {sn.replace("_", "__")}__pb2",
        )
        if patched != text:
            grpc_stub.write_text(patched, encoding="utf-8")
            print("Patched grpc stub import to use package-relative path")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# -----------------------------------------------------------------------
# pyproject.toml
# -----------------------------------------------------------------------

def _pyproject(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    return f'''[project]
name = "{sn}"
version = "{spec.version}"
description = "{spec.description or spec.service_name + ' microservice'}"
requires-python = ">=3.10"

dependencies = [
    "MicroserviceBase",
    "grpcio>=1.60.0",
    "grpcio-tools>=1.60.0",
    "grpcio-reflection>=1.60.0",
    "grpcio-health-checking>=1.60.0",
    "httpx>=0.25.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
]
'''


# -----------------------------------------------------------------------
# HTML/JS GUI
# -----------------------------------------------------------------------

def _gui_html(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    return f'''<div class="card" style="height: 100%; width: 100%; top: 0;">
  <div class="card-header">
    <h5 class="card-title">{svc}</h5>
  </div>
  <div class="card-body">
    <p>GUI for {svc}. Customize this HTML file.</p>
    <div id="{svc}Content"></div>
  </div>
</div>
'''


def _gui_js(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    return f'''/**
 * @fileoverview GUI plugin for {svc}.
 * @version 1.0.0
 */

var MM = window.MicroserviceManager;

function initialize{svc}() {{
  console.log("{svc} GUI initialized");
}}
'''


# =======================================================================
# Monorepo: one project, N services sharing one .proto
# =======================================================================

def generate_monorepo(spec: "ScaffoldSpec", services) -> Dict[str, str]:
    """
Render a Python monorepo scaffold: one project, N services, N
``run_<svc>`` console-script entry points.

Used when the user picks the ``monorepo`` layout in the Service
Creator wizard or sets ``monorepo: true`` in the CLI config.  Each
service gets its own ``main.py``, ``config.py``, ``context.py``,
domain + adapter stubs, and Nomad job spec; ``pyproject.toml`` lists
all entry points so ``pip install .`` produces N CLI commands.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Outer (project-level) scaffold specification.

* ``services``

  / *Condition*: required / *Type*: list /

  List of per-service ``ScaffoldSpec``-like objects.  Each entry's
  ``service_name``, ``methods``, and ``proto_package`` drive its own
  generated files.

**Returns:**

* ``files``

  / *Type*: Dict[str, str] /

  Map of relative-path → file-contents for the entire monorepo tree.
    """
    """Emit a Python monorepo scaffold with one entry-point per service.

    Layout:
        ProjectName/
          pyproject.toml          ← single project, lists each service
          README.md                  as a `[project.scripts]` entry point
          proto/
            <project>.proto        ← shared
            <project>_pb2.py       ← shared generated stubs
            <project>_pb2_grpc.py
          scripts/
            generate_protos.py
          deploy/
            <svc1>.nomad.hcl       ← one job per service
            <svc1>_service_config.json
            <svc2>.nomad.hcl
            ...
          src/
            <project_snake>/       ← Python package
              __init__.py
              <svc1>/              ← per-service module
                __init__.py
                main.py            ← entry point — `python -m <project>.<svc>`
                config.py          ← per-service env vars
                context.py         ← per-service DI
                domain/<svc>.py
                adapters/api/grpc_adapter.py
              <svc2>/
                ...

    All services share one .proto + one set of generated stubs.  Each
    service has its own env-var prefix (``<SVC1>_``), its own Nomad job,
    and its own asyncio entry point.  Mirrors the C++ monorepo layout
    (cpp_tmpl.generate_monorepo) but in Python.
    """
    files: Dict[str, str] = {}
    proj_snake = spec.snake_name        # e.g. "power_device_service"

    # ---- Shared proto (single file with N service blocks) ------------
    if spec.proto_content_override:
        files[f"proto/{proj_snake}.proto"] = spec.proto_content_override
    else:
        files[f"proto/{proj_snake}.proto"] = _mono_gen_proto(spec, services)
    files["proto/__init__.py"] = ""

    # ---- Top-level package files -------------------------------------
    files["pyproject.toml"] = _mono_pyproject(spec, services)
    files["scripts/generate_protos.py"] = _gen_protos_script(spec)
    files[f"src/{proj_snake}/__init__.py"] = ""

    # ---- Per-service module tree -------------------------------------
    for svc in services:
        svc_snake = _snake(svc.name)
        base = f"src/{proj_snake}/{svc_snake}"
        files[f"{base}/__init__.py"] = ""
        files[f"{base}/main.py"]    = _mono_main_py(spec, svc)
        files[f"{base}/config.py"]  = _mono_config_py(spec, svc)
        files[f"{base}/context.py"] = _mono_context_py(spec, svc)
        files[f"{base}/domain/__init__.py"] = ""
        files[f"{base}/domain/{svc_snake}.py"] = _mono_domain_py(spec, svc)
        files[f"{base}/adapters/__init__.py"] = ""
        files[f"{base}/adapters/api/__init__.py"] = ""
        files[f"{base}/adapters/api/grpc_adapter.py"] = _mono_grpc_adapter(spec, svc)

    # ---- Nomad jobs (one per service) --------------------------------
    if spec.gen_nomad:
        for svc in services:
            svc_snake = _snake(svc.name)
            files[f"deploy/{svc_snake}.nomad.hcl"] = _mono_nomad(spec, svc)
            files[f"deploy/{svc_snake}_service_config.json"] = _mono_service_config(spec, svc)

    # ---- README ------------------------------------------------------
    if spec.gen_readme:
        files["README.md"] = _mono_readme(spec, services)

    return files


def _mono_gen_proto(spec, services) -> str:
    """Fallback proto generator for the monorepo (when no override)."""
    pkg = spec.proto_package
    out = ['syntax = "proto3";', '', f'package {pkg};', '']
    for svc in services:
        out.append(f'service {svc.name} {{')
        for m in svc.methods:
            req = f"{m.name}Request"
            resp = f"{m.name}Response"
            stream = "stream " if m.server_streaming else ""
            out.append(f"  rpc {m.name}({req}) returns ({stream}{resp});")
        out.append('}')
        out.append('')
        for m in svc.methods:
            out.append(f'message {m.name}Request {{')
            for i, p in enumerate(m.params, 1):
                ptype = _proto_type(p.type)
                out.append(f'  {ptype} {p.name} = {i};')
            out.append('}')
            out.append(f'message {m.name}Response {{')
            out.append(f'  string result = 1;')
            out.append('}')
            out.append('')
    return '\n'.join(out)


def _proto_type(t: str) -> str:
    """Map our wizard types to proto3 scalar types."""
    return {
        'string': 'string',
        'int32': 'int32', 'int64': 'int64',
        'uint32': 'uint32', 'uint64': 'uint64',
        'bool': 'bool',
        'float': 'float', 'double': 'double',
        'bytes': 'bytes',
    }.get(t, 'string')


def _mono_pyproject(spec, services) -> str:
    """One pyproject.toml that registers each service as an entry point."""
    proj_snake = spec.snake_name
    proj_name_dash = proj_snake.replace('_', '-')
    scripts = []
    for svc in services:
        svc_snake = _snake(svc.name)
        scripts.append(f'{svc_snake.replace("_", "-")} = "{proj_snake}.{svc_snake}.main:run"')
    scripts_block = '\n'.join(scripts)

    return f'''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{proj_name_dash}"
version = "{spec.version}"
description = "{spec.description or spec.service_name + ' (monorepo with multiple services)'}"
requires-python = ">=3.10"
dependencies = [
    "MicroserviceBase",
    "grpcio>=1.60",
    "grpcio-tools>=1.60",
    "protobuf>=4.25",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

[project.scripts]
{scripts_block}

[tool.hatch.build.targets.wheel]
packages = ["src/{proj_snake}", "proto"]
'''


def _mono_main_py(spec, svc) -> str:
    """Entry point for one service inside the monorepo."""
    proj_snake = spec.snake_name
    svc_snake = _snake(svc.name)
    header = python_file_header(
        "main.py",
        f"Entry point for {svc.name} (one service in the {spec.service_name}\n"
        f"monorepo).  Reusable shape: each service has its own main.py /\n"
        f"context.py / config.py and runs as `python -m {proj_snake}.{svc_snake}.main`.",
    )
    return f'''{header}\
"""
Entry point for {svc.name} (part of {spec.service_name}).
"""

from __future__ import annotations

import asyncio
import logging

from {proj_snake}.{svc_snake}.context import create_context
from proto import {proj_snake}_pb2, {proj_snake}_pb2_grpc  # type: ignore[import-not-found]

from MicroserviceBase.runtime import ServiceRunner, ServicerEntry


async def amain() -> None:
    """
Build the per-service context and serve the gRPC server until shutdown.

**Returns:**

(*no returns*)
    """
    ctx = create_context()

    logging.basicConfig(
        level=ctx.settings.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    full_service_name = {proj_snake}_pb2.DESCRIPTOR.services_by_name[
        "{svc.name}"
    ].full_name

    runner = ServiceRunner(
        servicers=[
            ServicerEntry(
                register_fn={proj_snake}_pb2_grpc.add_{svc.name}Servicer_to_server,
                full_service_name=full_service_name,
                servicer=ctx.grpc_adapter,
            )
        ],
        settings=ctx.settings,
        tags=["v1"],
    )
    await runner.serve_forever()


def run() -> None:
    """
Console-script entry point declared in ``pyproject.toml``.  After
``pip install .`` you get a CLI command per service.

**Returns:**

(*no returns*)
    """
    asyncio.run(amain())


if __name__ == "__main__":
    run()
'''


def _mono_config_py(spec, svc) -> str:
    svc_snake = _snake(svc.name)
    prefix = svc_snake.upper() + "_"
    header = python_file_header(
        "config.py",
        f"Pydantic settings for the {svc.name} sub-service.\n"
        f"Reads env vars prefixed with `{prefix}`.",
    )
    return f'''{header}\
"""
Settings for {svc.name}.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from MicroserviceBase.runtime import BaseServiceSettings


class Settings(BaseServiceSettings):
    """
Per-service settings inside the monorepo.  Inherits standard fields
from :class:`BaseServiceSettings`; add service-specific fields below
as plain class attributes.

**Attributes:**

* ``service_name``

  / *Type*: str / *Default*: "{svc_snake}" /

  Logical name registered with Consul.
    """
    model_config = SettingsConfigDict(
        env_prefix="{prefix}",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "{svc_snake}"
'''


def _mono_context_py(spec, svc) -> str:
    proj_snake = spec.snake_name
    svc_snake = _snake(svc.name)
    cls = svc.name
    header = python_file_header(
        "context.py",
        f"Dependency-injection composition root for the {svc.name}\n"
        f"sub-service.",
    )
    return f'''{header}\
"""
Dependency injection for {svc.name}.
"""

from __future__ import annotations

from dataclasses import dataclass

from {proj_snake}.{svc_snake}.adapters.api.grpc_adapter import {cls}GrpcAdapter
from {proj_snake}.{svc_snake}.config import Settings
from {proj_snake}.{svc_snake}.domain.{svc_snake} import {cls}


@dataclass
class Context:
    """
Per-service DI bag.

**Attributes:**

* ``settings``

  / *Type*: Settings /

  Service-specific settings.

* ``domain``

  / *Type*: {cls} /

  Pure-business-logic instance.

* ``grpc_adapter``

  / *Type*: {cls}GrpcAdapter /

  gRPC inbound adapter.
    """
    settings: Settings
    domain: {cls}
    grpc_adapter: {cls}GrpcAdapter


def create_context() -> Context:
    """
Build the per-service :class:`Context`.

**Returns:**

* ``ctx``

  / *Type*: Context /

  Fully-wired context ready for ``ServiceRunner``.
    """
    settings = Settings()
    domain = {cls}()
    grpc_adapter = {cls}GrpcAdapter(domain)
    return Context(settings=settings, domain=domain, grpc_adapter=grpc_adapter)
'''


def _mono_domain_py(spec, svc) -> str:
    cls = svc.name
    svc_snake = _snake(svc.name)

    methods = ""
    for m in svc.methods:
        params = ", ".join(f"{p.name}: str" for p in m.params)
        if params:
            params = ", " + params

        arg_section = ""
        if m.params:
            arg_section = "\n**Arguments:**\n" + "".join(
                f"\n* ``{p.name}``\n"
                f"\n  / *Condition*: required / *Type*: str /\n"
                f"\n  TODO: describe ``{p.name}``.\n"
                for p in m.params
            )

        if m.server_streaming:
            methods += f'''
    async def {_snake(m.name)}(self{params}):
        """
{m.name} — TODO: describe what this server-streaming RPC does.
{arg_section}
**Yields:**

* ``event``

  / *Type*: dict /

  TODO: describe each event.  The default stub yields one
  ``{{"result": "not implemented"}}`` and stops.
        """
        # TODO: implement.
        yield {{"result": "not implemented"}}
'''
        else:
            methods += f'''
    async def {_snake(m.name)}(self{params}) -> str:
        """
{m.name} — TODO: describe what this RPC does.
{arg_section}
**Returns:**

* ``result``

  / *Type*: str /

  TODO: describe the return value.  Default stub returns
  ``"not implemented"``.
        """
        # TODO: implement.
        return "not implemented"
'''

    header = python_file_header(
        f"{svc_snake}.py",
        f"Pure business logic for the {svc.name} sub-service.\n"
        f"Zero I/O — no gRPC, no Consul, no HTTP.  Inbound traffic enters\n"
        f"through the gRPC adapter at adapters/api/grpc_adapter.py.",
    )
    return f'''{header}\
"""
Pure business logic for {svc.name} — no gRPC, no I/O.
"""

from __future__ import annotations

from typing import AsyncIterator


class {cls}:
    """
Domain service for {svc.name}.  One method per RPC.  Edit bodies to
plug in real logic.
    """
{methods if methods else "    pass"}
'''


def _mono_grpc_adapter(spec, svc) -> str:
    proj_snake = spec.snake_name
    cls = svc.name

    methods = ""
    for m in svc.methods:
        if m.server_streaming:
            methods += f'''
    async def {m.name}(self, request, context):
        """
Handle a server-streaming {m.name} RPC.

**Arguments:**

* ``request``

  / *Condition*: required / *Type*: {m.name}Request /

  Proto request message.

* ``context``

  / *Condition*: required / *Type*: grpc.aio.ServicerContext /

  Per-call context.

**Yields:**

* ``response``

  / *Type*: {m.name}Response /

  One proto message per event.
        """
        async for item in self._domain.{_snake(m.name)}():
            yield {proj_snake}_pb2.{m.name}Response(result=str(item))
'''
        else:
            methods += f'''
    async def {m.name}(self, request, context):
        """
Handle a unary {m.name} RPC.

**Arguments:**

* ``request``

  / *Condition*: required / *Type*: {m.name}Request /

  Proto request message.

* ``context``

  / *Condition*: required / *Type*: grpc.aio.ServicerContext /

  Per-call context.

**Returns:**

* ``response``

  / *Type*: {m.name}Response /

  Proto response message.
        """
        result = await self._domain.{_snake(m.name)}()
        return {proj_snake}_pb2.{m.name}Response(result=str(result))
'''

    header = python_file_header(
        "grpc_adapter.py",
        f"gRPC inbound adapter for {svc.name} (one service in the\n"
        f"{spec.service_name} monorepo).",
    )
    return f'''{header}\
"""
gRPC adapter for {svc.name}.
"""

from __future__ import annotations

from {proj_snake}.{_snake(svc.name)}.domain.{_snake(svc.name)} import {cls}
from proto import {proj_snake}_pb2, {proj_snake}_pb2_grpc  # type: ignore[import-not-found]


class {cls}GrpcAdapter({proj_snake}_pb2_grpc.{cls}Servicer):
    """
gRPC servicer for {svc.name}.  Translates proto messages to domain
calls.  One method per RPC.
    """

    def __init__(self, domain: {cls}) -> None:
        """
Wire the adapter to the domain service.

**Arguments:**

* ``domain``

  / *Condition*: required / *Type*: {cls} /

  Pure-business-logic instance for this service.
        """
        self._domain = domain
{methods if methods else "    pass"}
'''


def _mono_nomad(spec, svc) -> str:
    """Nomad HCL for one service inside the monorepo."""
    svc_snake = _snake(svc.name)
    prefix = svc_snake.upper() + "_"
    return f'''job "{svc_snake}" {{
  datacenters = ["{spec.nomad_dc}"]
  type        = "service"

  group "{svc_snake}" {{
    network {{
      port "grpc" {{}}
    }}

    task "server" {{
      driver = "{spec.nomad_driver}"

      config {{
        command = "python"
        args    = ["-m", "{spec.snake_name}.{svc_snake}.main"]
      }}

      env {{
        {prefix}GRPC_PORT     = "${{NOMAD_PORT_grpc}}"
        {prefix}CONSUL_ADDR   = "{spec.nomad_consul_addr}"
        {prefix}LOG_LEVEL     = "INFO"
      }}

      resources {{
        cpu    = {spec.nomad_cpu}
        memory = {spec.nomad_mem}
      }}
    }}
  }}
}}
'''


def _mono_service_config(spec, svc) -> str:
    """Per-service service_config.json for the monorepo."""
    import json as _json
    svc_snake = _snake(svc.name)
    return _json.dumps({
        "service_name": svc_snake,
        "version": spec.version,
        "description": svc.name,
        "language": "python",
        "monorepo_project": spec.snake_name,
    }, indent=2) + '\n'


def _mono_readme(spec, services) -> str:
    proj = spec.service_name
    proj_snake = spec.snake_name
    svc_lines = "\n".join(
        f"- **{s.name}** — {len(s.methods)} method(s), env prefix `{_snake(s.name).upper()}_`"
        for s in services
    )
    return f'''# {proj}

Python monorepo containing {len(services)} gRPC services that share a single
`.proto` file and one `pyproject.toml`.

## Services

{svc_lines}

## Layout

```
{proj}/
├── pyproject.toml          One project, N entry points
├── proto/
│   └── {proj_snake}.proto  Shared API definition
├── scripts/
│   └── generate_protos.py
├── src/{proj_snake}/
│   └── <service>/          One module per service
│       ├── main.py         Entry point — `python -m {proj_snake}.<svc>.main`
│       ├── config.py       Per-service env vars (`<SVC>_*`)
│       ├── context.py      Per-service DI factory
│       ├── domain/         Pure business logic
│       └── adapters/api/   gRPC adapter
├── deploy/                 One Nomad job per service
└── README.md
```

## Build

```bash
pip install -e .
python scripts/generate_protos.py
```

After install, each service is callable as a console script:

```bash
{services[0].name.lower() if services else 'service'}      # or: python -m {proj_snake}.{_snake(services[0].name) if services else 'svc'}.main
```

## Deploy

Each service ships its own `deploy/<svc>.nomad.hcl`:

```bash
{f'nomad job run deploy/{_snake(services[0].name)}.nomad.hcl' if services else '# nomad job run deploy/<service>.nomad.hcl'}
```

All services register with the same Consul agent by default
(`http://127.0.0.1:8500`).
'''


# =======================================================================
# Helpers
# =======================================================================

def _snake(name: str) -> str:
    """CamelCase → snake_case, keeping runs of capitals together.

    ``DoSomething`` → ``do_something``, ``PPSService`` → ``pps_service``,
    ``XMLParser`` → ``xml_parser``.
    """
    import re
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()
