"""Python service scaffold templates.

Generates the full project structure for a Python gRPC microservice
using the MicroserviceBase async runtime (ServiceRunner + Consul).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from .generator import ScaffoldSpec


def generate(spec: "ScaffoldSpec") -> Dict[str, str]:
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
    return f'''"""Entry point for {svc}."""

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
    return f'''"""Settings for {spec.service_name}."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from MicroserviceBase.runtime import BaseServiceSettings


class Settings(BaseServiceSettings):
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
    return f'''"""Dependency injection for {svc}."""

from __future__ import annotations

from dataclasses import dataclass

from adapters.api.grpc_adapter import {svc}GrpcAdapter
from config import Settings
from domain.{sn}_service import {cls}


@dataclass
class Context:
    settings: Settings
    domain: {cls}
    grpc_adapter: {svc}GrpcAdapter


def create_context() -> Context:
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

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"{p.name}: str" for p in m.params)
        if params:
            params = ", " + params
        if m.server_streaming:
            methods += f'''
    async def {_snake(m.name)}(self{params}):
        """TODO: implement {m.name}."""
        yield {{"result": "not implemented"}}
'''
        else:
            methods += f'''
    async def {_snake(m.name)}(self{params}) -> str:
        """TODO: implement {m.name}."""
        return "not implemented"
'''

    return f'''"""Pure business logic for {svc} — no gRPC, no I/O."""

from __future__ import annotations

from typing import AsyncIterator


class {cls}:
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

    methods = ""
    for m in spec.methods:
        param_reads = "\n".join(
            f"        _{p.name} = request.{p.name}"
            for p in m.params
        )
        args = ", ".join(f"_{p.name}" for p in m.params)
        if m.server_streaming:
            methods += f'''
    async def {m.name}(self, request, context):
{param_reads or "        pass"}
        async for item in self._domain.{_snake(m.name)}({args}):
            yield {sn}_pb2.{m.name}Response(result=str(item.get("result", "")))
'''
        else:
            methods += f'''
    async def {m.name}(self, request, context):
{param_reads or "        pass"}
        result = await self._domain.{_snake(m.name)}({args})
        return {sn}_pb2.{m.name}Response(result=str(result))
'''

    return f'''"""gRPC inbound adapter for {cls}."""

from __future__ import annotations

import grpc

{imports}

class {svc}GrpcAdapter({sn}_pb2_grpc.{svc}ServiceServicer):

    def __init__(self, domain: {cls}) -> None:
        self._domain = domain
{methods}
'''


# -----------------------------------------------------------------------
# scripts/generate_protos.py
# -----------------------------------------------------------------------

def _gen_protos_script(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    return f'''#!/usr/bin/env python3
"""Generate Python gRPC stubs from {sn}.proto."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
PROTO_DIR = SERVICE_ROOT / "proto"


def main() -> int:
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


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _snake(name: str) -> str:
    """CamelCase → snake_case, keeping runs of capitals together.

    ``DoSomething`` → ``do_something``, ``PPSService`` → ``pps_service``,
    ``XMLParser`` → ``xml_parser``.
    """
    import re
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()
